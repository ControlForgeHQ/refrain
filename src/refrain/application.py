"""Application coordination for one-shot and continuous presentation."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from PIL import Image

from .artifacts import ArtifactStoreError, PreparedImageArtifactSet, PreparedImageArtifactStore
from .config import ApplicationConfiguration, ApplicationConfigurationError, load_application_config
from .content import ContentLibraryError, load_content_library
from .display import DisplayBackend, DisplayBackendError, create_display_backend
from .eligibility import build_eligible_quotation_pool
from .persistence import (
    DailySnapshot,
    PersistentState,
    PersistentStateStore,
    ResolvedFont,
    SchedulingContext,
    StateCommitError,
    StateRecoveryError,
)
from .preparation import DailyImagePreparationError
from .recovery import recover_prepared_daily_images
from .scheduling import (
    SchedulingAction,
    SchedulingEvaluationError,
    evaluate_scheduling,
    resolve_reveal_stages,
)
from .selection import SelectionProposal, select_quotation
from .timekeeping import DisplayDayBoundaryObserver, next_scheduling_deadline, wait_for_scheduling_event

_LOGGER = logging.getLogger(__name__)
_IMAGE_SIZE = (1600, 1200)


class ApplicationError(Exception):
    """Raised when an application step fails; the message identifies the failed step."""


class _RetryableApplicationError(ApplicationError):
    """An operation that can be retried without replacing committed state."""


class NoEligibleQuotationError(ApplicationError):
    """Raised when no quotation is eligible for the requested display date."""


@dataclass(frozen=True)
class StartupResult:
    """The committed state and reveal stage presented by one startup cycle."""

    state: PersistentState
    presented_stage: int
    selected_initial_quotation: bool


BackendFactory = Callable[[ApplicationConfiguration], DisplayBackend]


def _default_backend_factory(configuration: ApplicationConfiguration) -> DisplayBackend:
    return create_display_backend(
        configuration.display_backend,
        image_server_host=configuration.image_server_host,
        image_server_port=configuration.image_server_port,
    )


def _resolve_font(
    configuration: ApplicationConfiguration, preferred: str | None, chooser: random.Random
) -> ResolvedFont:
    identifier = preferred
    if identifier is not None and identifier not in configuration.fonts:
        _LOGGER.warning("Requested font %r is not available; using a font from the default pool", identifier)
        identifier = None
    if identifier is None:
        identifier = chooser.choice(configuration.default_fonts)
    resource = configuration.fonts[identifier]
    try:
        with resource.path.open("rb") as font_file:
            return ResolvedFont(identifier, font_file.read())
    except (OSError, ValueError) as error:
        raise _RetryableApplicationError(f"cannot read font {identifier!r}: {error}") from error


def _select_snapshot(
    configuration: ApplicationConfiguration,
    display_date,
    chooser: random.Random,
    state: PersistentState | None = None,
) -> tuple[SelectionProposal, DailySnapshot]:
    try:
        entries = load_content_library(configuration.content_directory)
    except ContentLibraryError as error:
        raise _RetryableApplicationError(f"content library is invalid: {error}") from error

    pool = build_eligible_quotation_pool(entries, display_date)
    proposal = select_quotation(
        pool,
        () if state is None else state.repetition_history,
        chooser,
        base_revision=0 if state is None else state.revision,
    )
    candidate = proposal.selected_candidate
    if candidate is None:
        raise NoEligibleQuotationError(
            f"no quotation in {configuration.content_directory} is eligible for {display_date.isoformat()}; "
            "add an ordinary or matching date-specific entry"
        )

    entry = candidate.entry
    reveal = entry.reveal
    metadata: dict[str, object] = {"presentation_style": entry.presentation_style}
    if entry.source is not None:
        metadata["source"] = entry.source
    if entry.attribution is not None:
        metadata["attribution"] = entry.attribution
    region = configuration.presentation_region
    try:
        snapshot = DailySnapshot(
            quotation_text=candidate.text,
            quotation_identity=candidate.identity,
            font=_resolve_font(configuration, entry.font, chooser),
            presentation_metadata=metadata,
            reveal_schedule={
                "quotation": configuration.reveal.quotation.strftime("%H:%M"),
                "source": (reveal.source or configuration.reveal.source).strftime("%H:%M"),
                "attribution": (reveal.attribution or configuration.reveal.attribution).strftime("%H:%M"),
            },
            layout={
                "image_size": _IMAGE_SIZE,
                "presentation_region": {"x": region.x, "y": region.y, "width": region.width, "height": region.height},
                "min_font_size": configuration.min_font_size,
                "max_font_size": configuration.max_font_size,
            },
            scheduling=SchedulingContext(
                display_date,
                str(configuration.timezone),
                configuration.day_start.strftime("%H:%M"),
            ),
        )
        resolve_reveal_stages(snapshot)
    except (ValueError, TypeError) as error:
        raise ApplicationError(f"entry {entry.id!r} cannot produce a valid daily snapshot: {error}") from error
    return proposal, snapshot


def _commit_selection(
    store: PersistentStateStore, proposal: SelectionProposal, snapshot: DailySnapshot
) -> PersistentState:
    try:
        return store.commit(proposal, snapshot)
    except StateCommitError as error:
        if not error.published:
            raise _RetryableApplicationError(f"cannot commit selection: {error}") from error
        reloaded = _reload(store)
        if (
            reloaded is None
            or reloaded.revision != proposal.base_revision + 1
            or reloaded.snapshot != snapshot
            or reloaded.repetition_history != proposal.proposed_repetition_history
        ):
            raise ApplicationError(f"selection publication could not be confirmed: {error}") from error
        _LOGGER.warning("Selection was published but durability was not confirmed: %s", error)
        return reloaded


def _reload(store: PersistentStateStore) -> PersistentState | None:
    try:
        return store.load()
    except StateRecoveryError as error:
        if isinstance(error.__cause__, OSError):
            raise _RetryableApplicationError(f"cannot recover persistent state: {error}") from error
        raise ApplicationError(f"cannot recover persistent state: {error}") from error


def _persist_reveal_progress(store: PersistentStateStore, state: PersistentState, stage: int) -> PersistentState:
    try:
        return store.advance_reveal_progress(state.revision, stage)
    except StateCommitError as error:
        if error.published:
            reloaded = _reload(store)
            if reloaded is not None and reloaded.revision == state.revision and reloaded.highest_reveal_stage >= stage:
                _LOGGER.warning("Reveal progress was published but durability was not confirmed: %s", error)
                return reloaded
        raise _RetryableApplicationError(f"cannot persist reveal progress: {error}") from error


def present_prepared_stage(backend: DisplayBackend, artifacts: PreparedImageArtifactSet, stage: int) -> None:
    """Load one prepared stage, submit it to ``backend``, and release the loaded image."""
    try:
        image: Image.Image = artifacts.load_stage(stage)
    except ArtifactStoreError as error:
        raise _RetryableApplicationError(f"cannot load prepared image for stage {stage}: {error}") from error
    try:
        backend.update(image)
    except DisplayBackendError as error:
        raise _RetryableApplicationError(f"display update failed: {error}") from error
    finally:
        image.close()


def _load_configuration(config_file: str | Path) -> ApplicationConfiguration:
    try:
        return load_application_config(config_file)
    except ApplicationConfigurationError as error:
        raise ApplicationError(f"application configuration is invalid: {error}") from error


def _recover_images(state: PersistentState, artifact_store: PreparedImageArtifactStore) -> PreparedImageArtifactSet:
    try:
        return recover_prepared_daily_images(state, artifact_store, resolve_reveal_stages(state.snapshot))
    except DailyImagePreparationError as error:
        raise _RetryableApplicationError(f"cannot prepare daily images: {error}") from error
    except ArtifactStoreError as error:
        raise _RetryableApplicationError(f"cannot access prepared image artifacts: {error}") from error


def run_startup(
    config_file: str | Path,
    state_path: str | Path,
    artifact_root: str | Path,
    *,
    now: datetime | None = None,
    random_source: random.Random | None = None,
    backend_factory: BackendFactory = _default_backend_factory,
    keep_open: Callable[[str], None] | None = None,
) -> StartupResult:
    """Run one startup cycle: recover or select, prepare images, and present the required stage.

    ``now`` defaults to the current UTC time and exists so tests can control scheduling.
    ``keep_open`` is called with the backend name after a successful presentation while the
    backend is still open, for backends that only serve while the process runs.
    """
    configuration = _load_configuration(config_file)
    store = PersistentStateStore(Path(state_path).absolute())
    artifact_store = PreparedImageArtifactStore(Path(artifact_root).absolute())
    current_time = datetime.now(timezone.utc) if now is None else now

    state = _reload(store)
    try:
        decision = evaluate_scheduling(current_time, configuration, state)
        initial = decision.action is SchedulingAction.INITIAL_SELECTION
        if initial:
            assert decision.display_date is not None
            proposal, snapshot = _select_snapshot(
                configuration, decision.display_date, random_source or random.Random()
            )
            state = _commit_selection(store, proposal, snapshot)
            decision = evaluate_scheduling(current_time, configuration, state)
        elif decision.action is SchedulingAction.NEW_SELECTION:
            raise ApplicationError("a new daily selection is not supported by one-shot startup")
        assert state is not None and decision.required_reveal_stage is not None
        stage = decision.required_reveal_stage
    except SchedulingEvaluationError as error:
        raise ApplicationError(f"scheduling evaluation failed: {error}") from error

    artifacts = _recover_images(state, artifact_store)

    try:
        backend = backend_factory(configuration)
    except DisplayBackendError as error:
        raise ApplicationError(f"cannot initialize display backend: {error}") from error
    try:
        present_prepared_stage(backend, artifacts, stage)
        state = _persist_reveal_progress(store, state, stage)
        if keep_open is not None:
            keep_open(configuration.display_backend)
    except BaseException:
        try:
            backend.close()
        except Exception as close_error:
            _LOGGER.warning("Display backend cleanup failed: %s", close_error)
        raise
    try:
        backend.close()
    except DisplayBackendError as error:
        raise ApplicationError(f"display cleanup failed: {error}") from error
    return StartupResult(state=state, presented_stage=stage, selected_initial_quotation=initial)


def run_application(
    config_file: str | Path,
    state_path: str | Path,
    artifact_root: str | Path,
    *,
    shutdown_event: Event | None = None,
    random_source: random.Random | None = None,
    backend_factory: BackendFactory = _default_backend_factory,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic_clock: Callable[[], float] = time.monotonic,
    scheduling_wait: Callable[..., bool] = wait_for_scheduling_event,
) -> None:
    """Operate until shutdown, retaining one backend and authoritative committed state.

    Clocks, scheduling waits, and the shutdown event can be supplied for deterministic,
    hardware-independent integration tests. Retry waits use the event's interruptible
    ``wait(timeout)`` and monotonic elapsed time, independently of wall-clock changes.
    """
    configuration = _load_configuration(config_file)
    store = PersistentStateStore(Path(state_path).absolute())
    artifact_store = PreparedImageArtifactStore(Path(artifact_root).absolute())
    observer = DisplayDayBoundaryObserver(configuration)
    shutdown = shutdown_event if shutdown_event is not None else Event()
    chooser = random_source if random_source is not None else random.Random()
    backend: DisplayBackend | None = None
    artifacts: PreparedImageArtifactSet | None = None
    artifact_revision: int | None = None
    presented: tuple[int, int] | None = None
    last_failure: str | None = None
    retry_delay = 1.0
    _LOGGER.info("Starting continuous presentation")
    try:
        while not shutdown.is_set():
            try:
                # Reload before observing time, including after uncertain publication.
                state = _reload(store)
                now = wall_clock()
                boundary = observer.observe(now, monotonic_clock(), None if state is None else state.revision)
                decision = evaluate_scheduling(now, configuration, state, boundary)
                if decision.action in (SchedulingAction.INITIAL_SELECTION, SchedulingAction.NEW_SELECTION):
                    assert decision.display_date is not None
                    proposal, snapshot = _select_snapshot(configuration, decision.display_date, chooser, state)
                    state = _commit_selection(store, proposal, snapshot)
                    _LOGGER.info("Committed selection %s for %s", state.revision, state.snapshot.display_date)
                    # Reobserve after potentially slow I/O; never present obsolete intermediate stages.
                    continue
                assert state is not None and decision.required_reveal_stage is not None
                stage = decision.required_reveal_stage
                if presented is not None and presented[0] == state.revision:
                    stage = max(stage, presented[1])
                if artifacts is None or artifact_revision != state.revision:
                    artifacts = _recover_images(state, artifact_store)
                    artifact_revision = state.revision
                    try:
                        artifact_store.cleanup(state.revision)
                    except ArtifactStoreError as error:
                        _LOGGER.warning("Cannot clean obsolete prepared images: %s", error)
                    continue
                if backend is None:
                    try:
                        backend = backend_factory(configuration)
                    except DisplayBackendError as error:
                        raise _RetryableApplicationError(f"cannot initialize display backend: {error}") from error
                    continue
                if presented != (state.revision, stage):
                    try:
                        present_prepared_stage(backend, artifacts, stage)
                    except _RetryableApplicationError as error:
                        if isinstance(error.__cause__, ArtifactStoreError):
                            artifacts = None
                        raise
                    presented = (state.revision, stage)
                    _LOGGER.info("Presented selection %s stage %s", state.revision, stage)
                    if stage > state.highest_reveal_stage:
                        _persist_reveal_progress(store, state, stage)
                    continue
                if stage > state.highest_reveal_stage:
                    _persist_reveal_progress(store, state, stage)
                    continue
                if last_failure is not None:
                    _LOGGER.info("Application operation recovered")
                    last_failure = None
                retry_delay = 1.0
                deadline = next_scheduling_deadline(now, configuration, state)
                scheduling_wait(deadline, shutdown, wall_clock=wall_clock, monotonic_clock=monotonic_clock)
            except (_RetryableApplicationError, NoEligibleQuotationError, StateRecoveryError) as error:
                if isinstance(error, StateRecoveryError) and not isinstance(error.__cause__, OSError):
                    raise ApplicationError(f"cannot recover persistent state: {error}") from error
                message = str(error)
                if message != last_failure:
                    _LOGGER.warning("Application operation failed; retrying: %s", message)
                    last_failure = message
                retry_at = monotonic_clock() + retry_delay
                while not shutdown.is_set():
                    remaining = retry_at - monotonic_clock()
                    if remaining <= 0 or shutdown.wait(remaining):
                        break
                retry_delay = min(60.0, retry_delay * 2)
            except SchedulingEvaluationError as error:
                raise ApplicationError(f"scheduling evaluation failed: {error}") from error
    finally:
        if backend is not None:
            try:
                backend.close()
            except DisplayBackendError as error:
                _LOGGER.warning("Display backend cleanup failed: %s", error)
        _LOGGER.info("Continuous presentation stopped")


__all__ = [
    "ApplicationError",
    "NoEligibleQuotationError",
    "StartupResult",
    "present_prepared_stage",
    "run_startup",
    "run_application",
]

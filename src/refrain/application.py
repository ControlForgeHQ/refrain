"""Application coordination for one-shot and continuous presentation."""

from __future__ import annotations

import logging
import math
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from PIL import Image

from .artifacts import ArtifactStoreError, PreparedImageArtifactSet, PreparedImageArtifactStore
from .config import (
    ApplicationConfiguration,
    ApplicationConfigurationError,
    BackgroundResource,
    DecorationResource,
    DisplayBackendConfiguration,
    FontResource,
    load_application_config,
)
from .content import ContentLibraryError, load_content_library
from .display import DisplayBackend, DisplayBackendError, create_display_backend
from .display.coordinator import DisplayPublicationCoordinator
from .eligibility import build_eligible_quotation_pool
from .information_view import InformationViewPreparationError, prepare_information_view
from .persistence import (
    DailySnapshot,
    GlobalHistoryStore,
    GlobalHistoryWriteError,
    PersistentState,
    PersistentStateStore,
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
_INFORMATION_VIEW_IDENTITY = (0, -1)
_INFORMATION_VIEW_PUBLICATION_TIMEOUT = 60.0


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


BackendFactory = Callable[[DisplayBackendConfiguration], DisplayBackend]


class _InformationPublicationWakeEvent:
    def __init__(
        self,
        coordinator: DisplayPublicationCoordinator,
        identity: tuple[int, int],
        shutdown: Event,
    ) -> None:
        self._coordinator = coordinator
        self._identity = identity
        self._shutdown = shutdown

    def is_set(self) -> bool:
        return self._shutdown.is_set() or self._coordinator.has_successful_publication(self._identity)

    def wait(self, timeout: float | None = None) -> bool:
        self._coordinator.wait_for_any_publication(
            self._identity,
            timeout,
            cancellation_event=self._shutdown,
        )
        return self.is_set()


def _default_backend_factory(configuration: DisplayBackendConfiguration) -> DisplayBackend:
    return create_display_backend(
        configuration.type,
        image_server_host=configuration.host,
        image_server_port=configuration.port,
    )


def _resolve_font(configuration: ApplicationConfiguration, preferred: str | None, chooser: random.Random) -> str:
    identifier = preferred
    if identifier is not None and identifier not in configuration.fonts:
        _LOGGER.warning("Requested font %r is not available; using a font from the default pool", identifier)
        identifier = None
    if identifier is None:
        if not configuration.default_fonts:
            raise ApplicationError(
                "no usable font remains in layout.fonts.default; register a usable configured font "
                "or select a valid registered font in the content entry"
            )
        identifier = chooser.choice(configuration.default_fonts)
    return identifier


def _resolve_background(configuration: ApplicationConfiguration, preferred: str | None, chooser: random.Random) -> str:
    if preferred == "none" or preferred in configuration.backgrounds:
        return preferred
    if preferred is not None:
        _LOGGER.warning("Requested background %r is not available; using the default background pool", preferred)
    return chooser.choice(configuration.default_backgrounds)


def _resolve_decoration(configuration: ApplicationConfiguration, preferred: str | None, chooser: random.Random) -> str:
    if preferred == "none" or preferred in configuration.decorations:
        return preferred
    if preferred is not None:
        _LOGGER.warning("Requested decoration %r is not available; using the default decoration pool", preferred)
    return chooser.choice(configuration.default_decorations)


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
    history = set() if state is None else set(state.repetition_history)
    history.intersection_update(quotation.identity for entry in entries for quotation in entry.quotations)
    proposal = select_quotation(
        pool,
        history,
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
    decoration_identifier = _resolve_decoration(configuration, entry.decoration, chooser)
    decoration = configuration.decorations.get(decoration_identifier)
    font_preference = entry.font
    if font_preference is not None and font_preference not in configuration.fonts:
        _LOGGER.warning("Requested font %r is not available; checking decoration preference", font_preference)
        font_preference = None
    if font_preference is None and decoration is not None:
        font_preference = decoration.font
    background_preference = entry.background
    if (
        background_preference is not None
        and background_preference != "none"
        and background_preference not in configuration.backgrounds
    ):
        _LOGGER.warning(
            "Requested background %r is not available; checking decoration preference", background_preference
        )
        background_preference = None
    if background_preference is None and decoration is not None:
        background_preference = decoration.background
    region = (
        configuration.presentation_region
        if decoration is None
        else (decoration.presentation_region or configuration.presentation_region)
    )
    try:
        snapshot = DailySnapshot(
            quotation_text=candidate.text,
            quotation_identity=candidate.identity,
            font_identifier=_resolve_font(configuration, font_preference, chooser),
            background_identifier=_resolve_background(configuration, background_preference, chooser),
            decoration_identifier=decoration_identifier,
            presentation_metadata=metadata,
            reveal_schedule={
                "quotation": configuration.day_start.strftime("%H:%M"),
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
        if not error.recoverable:
            raise ApplicationError(f"display update failed: {error}") from error
        raise _RetryableApplicationError(f"display update failed: {error}") from error
    finally:
        image.close()


def _load_configuration(config_file: str | Path) -> ApplicationConfiguration:
    try:
        return load_application_config(config_file)
    except ApplicationConfigurationError as error:
        raise ApplicationError(f"application configuration is invalid: {error}") from error


def _recover_images(
    state: PersistentState,
    artifact_store: PreparedImageArtifactStore,
    font_registry: Mapping[str, FontResource],
    background_registry: Mapping[str, BackgroundResource] | None = None,
    decoration_registry: Mapping[str, DecorationResource] | None = None,
) -> PreparedImageArtifactSet:
    try:
        return recover_prepared_daily_images(
            state,
            artifact_store,
            resolve_reveal_stages(state.snapshot),
            font_registry,
            background_registry,
            decoration_registry,
        )
    except DailyImagePreparationError as error:
        raise _RetryableApplicationError(f"cannot prepare daily images: {error}") from error
    except ArtifactStoreError as error:
        raise _RetryableApplicationError(f"cannot access prepared image artifacts: {error}") from error


def _create_history_store(
    state_path: Path,
    history_path: str | Path | None,
    history_segment_size: int,
    history_max_segments: int,
) -> GlobalHistoryStore:
    path = state_path.with_name("global-history.jsonl") if history_path is None else Path(history_path).absolute()
    state_file = state_path.resolve()
    resolved_history_path = path.resolve()
    segments = re.compile(rf"{re.escape(path.stem)}\.\d+{re.escape(path.suffix)}\Z")
    if resolved_history_path == state_file or (
        path.parent.resolve() == state_path.parent.resolve() and segments.fullmatch(state_path.name)
    ):
        raise ValueError("global-history path and its rotated segments must not overlap the operational state file")
    return GlobalHistoryStore(path, max_segment_size=history_segment_size, max_segments=history_max_segments)


def _record_selection_history(history_store: GlobalHistoryStore, state: PersistentState) -> None:
    try:
        history_store.record(state)
    except GlobalHistoryWriteError as error:
        _LOGGER.warning("Committed selection %s was not recorded in global history: %s", state.revision, error)


def run_startup(
    config_file: str | Path,
    state_path: str | Path,
    artifact_root: str | Path,
    *,
    now: datetime | None = None,
    random_source: random.Random | None = None,
    history_path: str | Path | None = None,
    history_segment_size: int = 1_048_576,
    history_max_segments: int = 20,
    backend_factory: BackendFactory = _default_backend_factory,
    keep_open: Callable[[str], None] | None = None,
    wall_clock: Callable[[], datetime] | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], None] = time.sleep,
) -> StartupResult:
    """Run one startup cycle: recover or select, prepare images, and publish the required stage.

    ``now`` defaults to the current UTC time and exists so tests can control scheduling.
    ``keep_open`` is called with one successfully updated serving backend name while its
    backend remains open.
    """
    configuration = _load_configuration(config_file)
    store = PersistentStateStore(Path(state_path).absolute())
    history_store = _create_history_store(store.path, history_path, history_segment_size, history_max_segments)
    artifact_store = PreparedImageArtifactStore(Path(artifact_root).absolute())
    current_time = (
        wall_clock() if now is None and wall_clock is not None else (datetime.now(timezone.utc) if now is None else now)
    )

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
            _record_selection_history(history_store, state)
            decision = evaluate_scheduling(current_time, configuration, state)
        elif decision.action is SchedulingAction.NEW_SELECTION:
            raise ApplicationError("a new daily selection is not supported by one-shot startup")
        assert state is not None and decision.required_reveal_stage is not None
        stage = decision.required_reveal_stage
    except SchedulingEvaluationError as error:
        raise ApplicationError(f"scheduling evaluation failed: {error}") from error

    if stage > state.highest_reveal_stage:
        state = _persist_reveal_progress(store, state, stage)
    artifacts = _recover_images(
        state,
        artifact_store,
        configuration.fonts,
        configuration.backgrounds,
        configuration.decorations,
    )
    coordinator = DisplayPublicationCoordinator(
        configuration.display_backends,
        backend_factory,
        retry=False,
        monotonic_clock=monotonic_clock,
    )
    try:
        if configuration.information_view_duration > 0:
            try:
                information_image = prepare_information_view(configuration)
            except InformationViewPreparationError as error:
                _LOGGER.warning("Cannot prepare information view; proceeding to daily presentation: %s", error)
            else:
                coordinator.publish(_INFORMATION_VIEW_IDENTITY, information_image)
                if coordinator.wait_for_any_publication(
                    _INFORMATION_VIEW_IDENTITY,
                    timeout=_INFORMATION_VIEW_PUBLICATION_TIMEOUT,
                ):
                    acknowledged_at = coordinator.first_successful_publication_time(_INFORMATION_VIEW_IDENTITY)
                    if acknowledged_at is not None:
                        remaining = configuration.information_view_duration - (monotonic_clock() - acknowledged_at)
                        if remaining > 0:
                            wait(remaining)
                else:
                    _LOGGER.warning(
                        "Information view was not published within the initial attempt period; "
                        "proceeding to daily presentation"
                    )
            current_time = wall_clock() if wall_clock is not None else datetime.now(timezone.utc)
            try:
                decision = evaluate_scheduling(current_time, configuration, state)
                assert decision.required_reveal_stage is not None
                stage = decision.required_reveal_stage
            except SchedulingEvaluationError as error:
                raise ApplicationError(f"scheduling evaluation failed after information view: {error}") from error
        if stage > state.highest_reveal_stage:
            state = _persist_reveal_progress(store, state, stage)
        try:
            image = artifacts.load_stage(stage)
        except ArtifactStoreError as error:
            raise ApplicationError(f"cannot load prepared image for stage {stage}: {error}") from error
        identity = (state.revision, stage)
        coordinator.publish(identity, image)
        if not coordinator.wait_for_publication(identity):
            raise ApplicationError("all configured display destinations are unavailable")
        if keep_open is not None:
            for backend_configuration in configuration.display_backends:
                if (
                    backend_configuration.type in {"window", "image-server"}
                    and coordinator.acknowledgements[backend_configuration.type] == identity
                ):
                    keep_open(backend_configuration.type)
                    break
    finally:
        coordinator.close()
    return StartupResult(state=state, presented_stage=stage, selected_initial_quotation=initial)


def run_application(
    config_file: str | Path,
    state_path: str | Path,
    artifact_root: str | Path,
    *,
    shutdown_event: Event | None = None,
    random_source: random.Random | None = None,
    history_path: str | Path | None = None,
    history_segment_size: int = 1_048_576,
    history_max_segments: int = 20,
    backend_factory: BackendFactory = _default_backend_factory,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic_clock: Callable[[], float] = time.monotonic,
    scheduling_wait: Callable[..., bool] = wait_for_scheduling_event,
) -> None:
    """Operate until shutdown, retaining independent display workers and authoritative state.

    Clocks, scheduling waits, and the shutdown event can be supplied for deterministic,
    hardware-independent integration tests. Retry waits use the event's interruptible
    ``wait(timeout)`` and monotonic elapsed time, independently of wall-clock changes.
    """
    configuration = _load_configuration(config_file)
    store = PersistentStateStore(Path(state_path).absolute())
    history_store = _create_history_store(store.path, history_path, history_segment_size, history_max_segments)
    artifact_store = PreparedImageArtifactStore(Path(artifact_root).absolute())
    observer = DisplayDayBoundaryObserver(configuration)
    shutdown = shutdown_event if shutdown_event is not None else Event()
    chooser = random_source if random_source is not None else random.Random()
    coordinator: DisplayPublicationCoordinator | None = None
    artifacts: PreparedImageArtifactSet | None = None
    artifact_revision: int | None = None
    latest_desired: tuple[int, int] | None = None
    pending_history: tuple[int, DailySnapshot, frozenset[str]] | None = None
    last_failure: str | None = None
    retry_delay = 1.0
    information_view_done = configuration.information_view_duration == 0
    information_view_image: Image.Image | None = None
    information_view_requested = False
    information_view_attempt_started: float | None = None
    information_view_started: float | None = None
    information_view_acknowledgement_logged = False
    _LOGGER.info("Starting continuous presentation")
    try:
        while not shutdown.is_set():
            try:
                if coordinator is not None and information_view_requested and information_view_started is None:
                    information_view_started = coordinator.first_successful_publication_time(_INFORMATION_VIEW_IDENTITY)
                # Reload before observing time, including after uncertain publication.
                state = _reload(store)
                if pending_history is not None and state is not None:
                    revision, snapshot, repetition_history = pending_history
                    if (
                        state.revision == revision
                        and state.snapshot == snapshot
                        and state.repetition_history == repetition_history
                    ):
                        _record_selection_history(history_store, state)
                        pending_history = None
                now = wall_clock()
                boundary = observer.observe(now, monotonic_clock(), None if state is None else state.revision)
                decision = evaluate_scheduling(now, configuration, state, boundary)
                if decision.action in (SchedulingAction.INITIAL_SELECTION, SchedulingAction.NEW_SELECTION):
                    assert decision.display_date is not None
                    proposal, snapshot = _select_snapshot(configuration, decision.display_date, chooser, state)
                    pending_history = (
                        proposal.base_revision + 1,
                        snapshot,
                        proposal.proposed_repetition_history,
                    )
                    state = _commit_selection(store, proposal, snapshot)
                    _record_selection_history(history_store, state)
                    pending_history = None
                    _LOGGER.info("Committed selection %s for %s", state.revision, state.snapshot.display_date)
                    # Reobserve after potentially slow I/O; never present obsolete intermediate stages.
                    continue
                assert state is not None and decision.required_reveal_stage is not None
                stage = decision.required_reveal_stage
                if latest_desired is not None and latest_desired[0] == state.revision:
                    stage = max(stage, latest_desired[1])
                latest_desired = (state.revision, stage)
                if artifacts is None or artifact_revision != state.revision:
                    if coordinator is not None:
                        desired_identity = coordinator.desired_identity
                        if (
                            desired_identity is not None
                            and desired_identity != _INFORMATION_VIEW_IDENTITY
                            and desired_identity[0] != state.revision
                        ):
                            coordinator.clear_desired()
                    artifacts = _recover_images(
                        state,
                        artifact_store,
                        configuration.fonts,
                        configuration.backgrounds,
                        configuration.decorations,
                    )
                    artifact_revision = state.revision
                    try:
                        artifact_store.cleanup(state.revision)
                    except ArtifactStoreError as error:
                        _LOGGER.warning("Cannot clean obsolete prepared images: %s", error)
                    continue
                if stage > state.highest_reveal_stage:
                    state = _persist_reveal_progress(store, state, stage)
                identity = (state.revision, stage)
                if coordinator is None:
                    coordinator = DisplayPublicationCoordinator(
                        configuration.display_backends,
                        backend_factory,
                        all_unavailable_event=shutdown,
                        monotonic_clock=monotonic_clock,
                    )
                if coordinator.all_unavailable:
                    raise ApplicationError("all configured display destinations are unavailable")
                if not information_view_done:
                    current_monotonic = monotonic_clock()
                    if information_view_requested:
                        if information_view_started is None:
                            information_view_started = coordinator.first_successful_publication_time(
                                _INFORMATION_VIEW_IDENTITY
                            )
                        if information_view_started is not None and not information_view_acknowledgement_logged:
                            _LOGGER.info("Information view publication acknowledged")
                            information_view_acknowledgement_logged = True
                        if (
                            information_view_started is not None
                            and current_monotonic - information_view_started >= configuration.information_view_duration
                        ):
                            information_view_done = True
                            _LOGGER.info("Information view duration expired")
                            continue
                        elif (
                            information_view_started is None
                            and information_view_attempt_started is not None
                            and current_monotonic - information_view_attempt_started
                            >= _INFORMATION_VIEW_PUBLICATION_TIMEOUT
                        ):
                            information_view_done = True
                            _LOGGER.warning("Information view was not published within the initial attempt period")
                    if not information_view_done and information_view_image is None:
                        try:
                            information_view_image = prepare_information_view(configuration)
                        except InformationViewPreparationError as error:
                            _LOGGER.warning(
                                "Cannot prepare information view; proceeding to daily presentation: %s",
                                error,
                            )
                            information_view_done = True
                    if not information_view_done and not information_view_requested:
                        assert information_view_image is not None
                        coordinator.publish(_INFORMATION_VIEW_IDENTITY, information_view_image)
                        information_view_image = None
                        information_view_requested = True
                        information_view_attempt_started = monotonic_clock()
                        _LOGGER.info("Requested startup information view")
                        continue
                    if not information_view_done:
                        deadline = next_scheduling_deadline(now, configuration, state)
                        if information_view_started is None:
                            assert information_view_attempt_started is not None
                            remaining = _INFORMATION_VIEW_PUBLICATION_TIMEOUT - (
                                current_monotonic - information_view_attempt_started
                            )
                            wake_event = _InformationPublicationWakeEvent(
                                coordinator, _INFORMATION_VIEW_IDENTITY, shutdown
                            )
                        else:
                            remaining = configuration.information_view_duration - (
                                current_monotonic - information_view_started
                            )
                            wake_event = shutdown
                        information_deadline = now + timedelta(seconds=max(0.0, remaining))
                        if information_deadline.astimezone(timezone.utc) < deadline.astimezone(timezone.utc):
                            deadline = information_deadline
                        scheduling_wait(
                            deadline,
                            wake_event,
                            wall_clock=wall_clock,
                            monotonic_clock=monotonic_clock,
                        )
                        continue
                if coordinator.desired_identity != identity:
                    try:
                        image = artifacts.load_stage(stage)
                    except ArtifactStoreError as error:
                        artifacts = None
                        raise _RetryableApplicationError(
                            f"cannot load prepared image for stage {stage}: {error}"
                        ) from error
                    coordinator.publish(identity, image)
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
        if coordinator is not None:
            coordinator.close()
        if information_view_image is not None:
            information_view_image.close()
        _LOGGER.info("Continuous presentation stopped")
    if coordinator is not None and coordinator.all_unavailable:
        raise ApplicationError("all configured display destinations are unavailable")


def run_demo(
    config_file: str | Path,
    interval: float,
    *,
    shutdown_event: Event | None = None,
    random_source: random.Random | None = None,
    history_segment_size: int = 1_048_576,
    history_max_segments: int = 20,
    backend_factory: BackendFactory = _default_backend_factory,
    wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic_clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], bool] | None = None,
) -> None:
    """Cycle canonical stages using fresh session storage and a fixed eligibility date.

    Viewing durations start at the coordinator's first successful acknowledgement.
    Tests may supply clocks and an interruptible wait; by default waits use the
    shutdown event, which also wakes when every display destination is lost.
    """
    if not math.isfinite(interval) or interval <= 0:
        raise ApplicationError("demo interval must be a positive finite number of seconds")
    configuration = _load_configuration(config_file)
    try:
        session = TemporaryDirectory(prefix="refrain-demo-")
    except OSError as error:
        raise ApplicationError(f"cannot create temporary demo storage: {error}") from error
    shutdown = shutdown_event if shutdown_event is not None else Event()
    pause = shutdown.wait if wait is None else wait
    chooser = random_source if random_source is not None else random.Random()
    coordinator: DisplayPublicationCoordinator | None = None
    _LOGGER.info("Starting demo presentation with a %s-second stage interval", interval)
    try:
        root = Path(session.name)
        store = PersistentStateStore(root / "state.json")
        try:
            history_store = _create_history_store(store.path, None, history_segment_size, history_max_segments)
        except ValueError as error:
            raise ApplicationError(f"invalid demo history retention: {error}") from error
        artifact_store = PreparedImageArtifactStore(root / "artifacts")
        try:
            display_date = evaluate_scheduling(wall_clock(), configuration, None).display_date
        except SchedulingEvaluationError as error:
            raise ApplicationError(f"cannot determine demo display date: {error}") from error
        assert display_date is not None
        coordinator = DisplayPublicationCoordinator(
            configuration.display_backends,
            backend_factory,
            all_unavailable_event=shutdown,
            monotonic_clock=monotonic_clock,
        )
        state: PersistentState | None = None
        pending_selection: tuple[SelectionProposal, DailySnapshot] | None = None
        selecting = True
        artifacts: PreparedImageArtifactSet | None = None
        stage = 0
        retry_delay = 1.0
        last_failure: str | None = None
        while not shutdown.is_set():
            try:
                if coordinator.all_unavailable:
                    raise ApplicationError("all configured display destinations are unavailable")
                if selecting:
                    if pending_selection is None:
                        state = _reload(store)
                        pending_selection = _select_snapshot(configuration, display_date, chooser, state)
                    state = _commit_selection(store, *pending_selection)
                    pending_selection = None
                    selecting = False
                    stage = 0
                    artifacts = None
                    _record_selection_history(history_store, state)
                    _LOGGER.info("Committed demo selection %s for %s", state.revision, display_date)
                    continue
                assert state is not None
                if artifacts is None:
                    artifacts = _recover_images(
                        state,
                        artifact_store,
                        configuration.fonts,
                        configuration.backgrounds,
                        configuration.decorations,
                    )
                    try:
                        artifact_store.cleanup(state.revision)
                    except ArtifactStoreError as error:
                        _LOGGER.warning("Cannot clean obsolete demo images: %s", error)
                    continue
                if stage > state.highest_reveal_stage:
                    state = _persist_reveal_progress(store, state, stage)
                identity = (state.revision, stage)
                if coordinator.desired_identity != identity:
                    try:
                        image = artifacts.load_stage(stage)
                    except ArtifactStoreError as error:
                        artifacts = None
                        raise _RetryableApplicationError(
                            f"cannot load prepared demo image for stage {stage}: {error}"
                        ) from error
                    coordinator.publish(identity, image)
                if not coordinator.wait_for_any_publication(identity, cancellation_event=shutdown):
                    continue
                acknowledged_at = coordinator.first_successful_publication_time(identity)
                assert acknowledged_at is not None
                if last_failure is not None:
                    _LOGGER.info("Demo operation recovered")
                    last_failure = None
                retry_delay = 1.0
                while not shutdown.is_set():
                    remaining = interval - (monotonic_clock() - acknowledged_at)
                    if remaining <= 0:
                        break
                    pause(min(remaining, 60.0))
                if shutdown.is_set():
                    break
                if stage + 1 < len(resolve_reveal_stages(state.snapshot)):
                    stage += 1
                else:
                    selecting = True
            except (_RetryableApplicationError, NoEligibleQuotationError, StateRecoveryError) as error:
                if isinstance(error, StateRecoveryError) and not isinstance(error.__cause__, OSError):
                    raise ApplicationError(f"cannot recover demo state: {error}") from error
                message = str(error)
                if message != last_failure:
                    _LOGGER.warning("Demo operation failed; retrying: %s", message)
                    last_failure = message
                retry_at = monotonic_clock() + retry_delay
                while not shutdown.is_set():
                    remaining = retry_at - monotonic_clock()
                    if remaining <= 0 or pause(remaining):
                        break
                retry_delay = min(60.0, retry_delay * 2)
    finally:
        try:
            if coordinator is not None:
                coordinator.close()
        finally:
            try:
                session.cleanup()
            except OSError as error:
                _LOGGER.warning("Cannot remove temporary demo storage: %s", error)
            _LOGGER.info("Demo presentation stopped")
    if coordinator is not None and coordinator.all_unavailable:
        raise ApplicationError("all configured display destinations are unavailable")


__all__ = [
    "ApplicationError",
    "NoEligibleQuotationError",
    "StartupResult",
    "present_prepared_stage",
    "run_startup",
    "run_application",
    "run_demo",
]

"""Application coordination for startup and initial daily presentation."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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

_LOGGER = logging.getLogger(__name__)
_IMAGE_SIZE = (1600, 1200)


class ApplicationError(Exception):
    """Raised when a startup step fails; the message identifies the failed step."""


class NoEligibleQuotationError(ApplicationError):
    """Raised when no quotation is eligible for the initial display date."""


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
        raise ApplicationError(f"cannot read font {identifier!r}: {error}") from error


def _select_initial_snapshot(
    configuration: ApplicationConfiguration,
    display_date,
    chooser: random.Random,
) -> tuple[SelectionProposal, DailySnapshot]:
    try:
        entries = load_content_library(configuration.content_directory)
    except ContentLibraryError as error:
        raise ApplicationError(f"content library is invalid: {error}") from error

    pool = build_eligible_quotation_pool(entries, display_date)
    proposal = select_quotation(pool, (), chooser, base_revision=0)
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


def _commit_initial_selection(
    store: PersistentStateStore, proposal: SelectionProposal, snapshot: DailySnapshot
) -> PersistentState:
    try:
        return store.commit(proposal, snapshot)
    except StateCommitError as error:
        if not error.published:
            raise ApplicationError(f"cannot commit the initial selection: {error}") from error
        reloaded = _reload(store)
        if reloaded is None or reloaded.revision != 1 or reloaded.snapshot != snapshot:
            raise ApplicationError(f"initial selection publication could not be confirmed: {error}") from error
        _LOGGER.warning("Initial selection was published but durability was not confirmed: %s", error)
        return reloaded


def _reload(store: PersistentStateStore) -> PersistentState | None:
    try:
        return store.load()
    except StateRecoveryError as error:
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
        raise ApplicationError(f"cannot persist reveal progress: {error}") from error


def present_prepared_stage(backend: DisplayBackend, artifacts: PreparedImageArtifactSet, stage: int) -> None:
    """Load one prepared stage, submit it to ``backend``, and release the loaded image."""
    try:
        image: Image.Image = artifacts.load_stage(stage)
    except ArtifactStoreError as error:
        raise ApplicationError(f"cannot load prepared image for stage {stage}: {error}") from error
    try:
        backend.update(image)
    except DisplayBackendError as error:
        raise ApplicationError(f"display update failed: {error}") from error
    finally:
        image.close()


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
    try:
        configuration = load_application_config(config_file)
    except ApplicationConfigurationError as error:
        raise ApplicationError(f"application configuration is invalid: {error}") from error
    store = PersistentStateStore(Path(state_path).absolute())
    artifact_store = PreparedImageArtifactStore(Path(artifact_root).absolute())
    current_time = datetime.now(timezone.utc) if now is None else now

    state = _reload(store)
    try:
        decision = evaluate_scheduling(current_time, configuration, state)
        initial = decision.action is SchedulingAction.INITIAL_SELECTION
        if initial:
            assert decision.display_date is not None
            proposal, snapshot = _select_initial_snapshot(
                configuration, decision.display_date, random_source or random.Random()
            )
            state = _commit_initial_selection(store, proposal, snapshot)
            decision = evaluate_scheduling(current_time, configuration, state)
        elif decision.action is SchedulingAction.NEW_SELECTION:
            raise ApplicationError("a new daily selection is not supported by one-shot startup")
        assert state is not None and decision.required_reveal_stage is not None
        stage = decision.required_reveal_stage
        stages = resolve_reveal_stages(state.snapshot)
    except SchedulingEvaluationError as error:
        raise ApplicationError(f"scheduling evaluation failed: {error}") from error

    try:
        artifacts = recover_prepared_daily_images(state, artifact_store, stages)
    except DailyImagePreparationError as error:
        raise ApplicationError(f"cannot prepare daily images: {error}") from error
    except ArtifactStoreError as error:
        raise ApplicationError(f"cannot access prepared image artifacts: {error}") from error

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


__all__ = [
    "ApplicationError",
    "NoEligibleQuotationError",
    "StartupResult",
    "present_prepared_stage",
    "run_startup",
]

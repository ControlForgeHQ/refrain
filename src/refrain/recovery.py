"""Hardware-independent recovery of committed daily presentation images."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .artifacts import (
    ArtifactValidationError,
    PreparedImageArtifactSet,
    PreparedImageArtifactStore,
)
from .config import BackgroundResource, DecorationResource, FontResource
from .persistence import PersistentState
from .preparation import DailyImagePreparationError, prepare_daily_images
from .renderer import CompositionVisibility, QuotationRenderError, _validate_reveal_stages


def recover_prepared_daily_images(
    state: PersistentState,
    artifact_store: PreparedImageArtifactStore,
    stages: Sequence[CompositionVisibility],
    font_registry: Mapping[str, FontResource],
    background_registry: Mapping[str, BackgroundResource] | None = None,
    decoration_registry: Mapping[str, DecorationResource] | None = None,
) -> PreparedImageArtifactSet:
    """Reuse or regenerate the complete images for an existing committed selection.

    ``stages`` is the complete ordered sequence of cumulative reveal stages. It is
    validated before reuse and is used for both artifact validation and regeneration.
    Generated images remain caller-owned until publication and are closed here,
    whether publication succeeds or fails. The committed state is never modified.
    A background registry is required unless the committed background is ``"none"``,
    including when prepared images can be reused. Missing committed decorations are
    omitted during regeneration without changing the saved presentation region.
    """
    if not isinstance(state, PersistentState):
        raise TypeError("state must be a PersistentState")
    if type(state.revision) is not int or state.revision <= 0:
        raise ValueError("state.revision must be a positive integer")
    if not isinstance(artifact_store, PreparedImageArtifactStore):
        raise TypeError("artifact_store must be a PreparedImageArtifactStore")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if background_registry is None and state.snapshot.background_identifier != "none":
        raise DailyImagePreparationError(
            "background_registry must be supplied when the committed background identifier is not 'none'"
        )
    if decoration_registry is None and state.snapshot.decoration_identifier != "none":
        raise DailyImagePreparationError(
            "decoration_registry must be supplied when the committed decoration identifier is not 'none'"
        )

    ordered_stages = tuple(stages)
    metadata = state.snapshot.presentation_metadata
    try:
        _validate_reveal_stages(
            ordered_stages,
            source_available=metadata.get("source") is not None,
            attribution_available=metadata.get("attribution") is not None,
            require_complete=True,
        )
    except QuotationRenderError as error:
        raise DailyImagePreparationError(str(error)) from error

    try:
        existing = artifact_store.load(state.revision, state.snapshot, stage_count=len(ordered_stages))
    except ArtifactValidationError:
        existing = None
    if existing is not None:
        return existing

    if decoration_registry is None:
        images = prepare_daily_images(state.snapshot, ordered_stages, font_registry, background_registry)
    else:
        images = prepare_daily_images(
            state.snapshot, ordered_stages, font_registry, background_registry, decoration_registry
        )
    try:
        return artifact_store.store(state.revision, state.snapshot, images)
    finally:
        for image in images:
            image.close()


__all__ = ["recover_prepared_daily_images"]

"""Hardware-independent recovery of committed daily presentation images."""

from __future__ import annotations

from collections.abc import Sequence

from .artifacts import (
    ArtifactValidationError,
    PreparedImageArtifactSet,
    PreparedImageArtifactStore,
)
from .persistence import PersistentState
from .preparation import DailyImagePreparationError, prepare_daily_images
from .renderer import CompositionVisibility, QuotationRenderError, _validate_reveal_stages


def recover_prepared_daily_images(
    state: PersistentState,
    artifact_store: PreparedImageArtifactStore,
    stages: Sequence[CompositionVisibility],
) -> PreparedImageArtifactSet:
    """Reuse or regenerate the complete images for an existing committed selection.

    ``stages`` is the complete ordered sequence of cumulative reveal stages. It is
    validated before reuse and is used for both artifact validation and regeneration.
    Generated images remain caller-owned until publication and are closed here,
    whether publication succeeds or fails. The committed state is never modified.
    """
    if not isinstance(state, PersistentState):
        raise TypeError("state must be a PersistentState")
    if type(state.revision) is not int or state.revision <= 0:
        raise ValueError("state.revision must be a positive integer")
    if not isinstance(artifact_store, PreparedImageArtifactStore):
        raise TypeError("artifact_store must be a PreparedImageArtifactStore")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")

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

    images = prepare_daily_images(state.snapshot, ordered_stages)
    try:
        return artifact_store.store(state.revision, state.snapshot, images)
    finally:
        for image in images:
            image.close()


__all__ = ["recover_prepared_daily_images"]

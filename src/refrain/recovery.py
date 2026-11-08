"""Hardware-independent recovery of committed daily presentation images."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import replace

from .artifacts import (
    ArtifactValidationError,
    PreparedImageArtifactSet,
    PreparedImageArtifactStore,
)
from .config import ApplicationConfiguration
from .geometry import PixelBounds
from .persistence import PersistentState
from .preparation import DailyImagePreparationError, prepare_daily_images
from .renderer import CompositionVisibility, QuotationRenderError, _validate_reveal_stages


def recover_prepared_daily_images(
    state: PersistentState,
    artifact_store: PreparedImageArtifactStore,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    *,
    chooser: random.Random | None = None,
) -> PreparedImageArtifactSet:
    """Reuse or regenerate the complete images for an existing committed selection.

    ``stages`` is the complete ordered sequence of cumulative reveal stages. It is
    validated before reuse and is used for both artifact validation and regeneration.
    Generated images remain caller-owned until publication and are closed here,
    whether publication succeeds or fails. The committed state is never modified.
    Current configuration and resources are consulted only when regeneration is needed.
    """
    if not isinstance(state, PersistentState):
        raise TypeError("state must be a PersistentState")
    if type(state.revision) is not int or state.revision <= 0:
        raise ValueError("state.revision must be a positive integer")
    if not isinstance(artifact_store, PreparedImageArtifactStore):
        raise TypeError("artifact_store must be a PreparedImageArtifactStore")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if not isinstance(configuration, ApplicationConfiguration):
        raise TypeError("configuration must be a validated ApplicationConfiguration")

    ordered_stages = tuple(stages)
    try:
        _validate_reveal_stages(
            ordered_stages,
            source_available=state.snapshot.source is not None,
            attribution_available=state.snapshot.attribution is not None,
            require_complete=True,
        )
    except QuotationRenderError as error:
        raise DailyImagePreparationError(str(error)) from error

    try:
        existing = artifact_store.load(state.revision, ordered_stages)
    except ArtifactValidationError:
        existing = None
    if existing is not None:
        return existing

    resolved_bounds: PixelBounds | None = None

    def remember_bounds(bounds: PixelBounds) -> None:
        nonlocal resolved_bounds
        resolved_bounds = bounds

    images = prepare_daily_images(
        state.snapshot,
        ordered_stages,
        configuration,
        chooser=chooser,
        on_resolved_bounds=remember_bounds,
    )
    try:
        artifact_set = artifact_store.store(state.revision, ordered_stages, images)
        return replace(artifact_set, literary_bounds=resolved_bounds)
    finally:
        for image in images:
            image.close()


__all__ = ["recover_prepared_daily_images"]

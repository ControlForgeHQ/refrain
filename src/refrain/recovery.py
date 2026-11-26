"""Hardware-independent recovery of committed daily presentation images."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import replace
from types import MappingProxyType

from .artifacts import (
    PreparedImageArtifactSet,
    PreparedImageArtifactStore,
)
from .checkpoint import validate_checkpoint
from .config import ApplicationConfiguration, PreparedImageVariantKey
from .geometry import PixelBounds, ResolvedOutputSpecification
from .persistence import PersistentState
from .preparation import DailyImagePreparationError, prepare_daily_images
from .renderer import CompositionVisibility, QuotationRenderError, _validate_reveal_stages


def recover_prepared_daily_images(
    state: PersistentState,
    artifact_store: PreparedImageArtifactStore,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    output_specifications: Sequence[ResolvedOutputSpecification | PreparedImageVariantKey],
    *,
    checkpoint: dict[str, object],
    qr_declaration: dict[str, object] | None,
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
    validate_checkpoint(checkpoint, state, require_presentation=True)

    ordered_stages = tuple(stages)
    if ordered_stages != tuple(stage.visibility for stage in state.snapshot.resolved_reveal_stages):
        raise DailyImagePreparationError("stages must match the committed reveal sequence")
    try:
        _validate_reveal_stages(
            ordered_stages,
            source_available=state.snapshot.source is not None,
            attribution_available=state.snapshot.attribution is not None,
            require_complete=True,
        )
    except QuotationRenderError as error:
        raise DailyImagePreparationError(str(error)) from error

    existing, missing = artifact_store.load_groups(
        state.revision,
        ordered_stages,
        output_specifications,
        snapshot=state.snapshot,
        checkpoint=checkpoint,
        qr_declaration=qr_declaration,
    )
    if not missing:
        return existing

    presentation_canvas_literary_bounds: dict[ResolvedOutputSpecification | PreparedImageVariantKey, PixelBounds] = {}
    prepared_metadata: dict[ResolvedOutputSpecification | PreparedImageVariantKey, tuple[dict[str, object], ...]] = {}

    def remember_bounds(
        variant_key: ResolvedOutputSpecification | PreparedImageVariantKey, bounds: PixelBounds
    ) -> None:
        presentation_canvas_literary_bounds[variant_key] = bounds

    def remember_metadata(
        variant_key: ResolvedOutputSpecification | PreparedImageVariantKey,
        metadata: tuple[dict[str, object], ...],
    ) -> None:
        prepared_metadata[variant_key] = metadata

    artifact_variants = dict(existing.variants)
    new_artifacts = existing
    choices_cache = {}
    for key in missing:

        def produce(write_stage):
            index = 0

            def persist_stage(stage_key, image):
                nonlocal index
                if stage_key != key or key not in prepared_metadata or index >= len(prepared_metadata[key]):
                    raise DailyImagePreparationError("prepared stages do not match the requested group")
                write_stage(image, prepared_metadata[key][index])
                index += 1

            prepare_daily_images(
                state.snapshot,
                ordered_stages,
                configuration,
                (key,),
                chooser=chooser,
                selection_revision=state.revision,
                canonical_presentation=checkpoint["presentation"],
                qr_declaration=qr_declaration,
                on_metadata=remember_metadata,
                on_resolved_bounds=remember_bounds,
                _on_stage=persist_stage,
                _choices_cache=choices_cache,
            )

        new_artifacts = artifact_store.store_generated(
            state.revision,
            ordered_stages,
            key,
            produce,
            snapshot=state.snapshot,
            checkpoint=checkpoint,
            qr_declaration=qr_declaration,
        )
        artifact_variants.update(new_artifacts.variants)
    for output_specification, bounds in presentation_canvas_literary_bounds.items():
        artifact_variants[output_specification] = replace(
            artifact_variants[output_specification],
            presentation_canvas_literary_bounds=bounds,
        )
    return replace(new_artifacts, variants=MappingProxyType(artifact_variants))


__all__ = ["recover_prepared_daily_images"]

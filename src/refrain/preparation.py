"""Hardware-independent preparation of daily presentation images."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PIL import Image

from .config import PresentationRegion
from .persistence import DailySnapshot
from .renderer import (
    CompositionVisibility,
    LiteraryComposition,
    QuotationRenderError,
    layout_composition,
    render_reveal_stages,
)

_BACKGROUND_COLOR = "#FFFFFF"
_BYLINE_GAP_FACTOR = 1.20


class DailyImagePreparationError(ValueError):
    """Raised when a daily snapshot cannot produce its requested images."""


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DailyImagePreparationError(f"snapshot.{field} must be a mapping")
    return value


def _resolve_presentation(
    snapshot: DailySnapshot,
) -> tuple[LiteraryComposition, PresentationRegion, tuple[int, int], int, int, str]:
    metadata = _require_mapping(snapshot.presentation_metadata, "presentation_metadata")
    style = metadata.get("presentation_style")
    if not isinstance(style, str) or style not in {"centered", "left-aligned"}:
        raise DailyImagePreparationError(
            "snapshot.presentation_metadata.presentation_style must be 'centered' or 'left-aligned'"
        )

    optional_fields: dict[str, str | None] = {}
    for field in ("source", "attribution"):
        value = metadata.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise DailyImagePreparationError(
                f"snapshot.presentation_metadata.{field} must be a nonempty string when supplied"
            )
        optional_fields[field] = value

    layout = _require_mapping(snapshot.layout, "layout")
    size = layout.get("image_size")
    if (
        not isinstance(size, (tuple, list))
        or len(size) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in size)
    ):
        raise DailyImagePreparationError("snapshot.layout.image_size must contain two positive integer dimensions")

    region_data = _require_mapping(layout.get("presentation_region"), "layout.presentation_region")
    region_fields = ("x", "y", "width", "height")
    missing_region_fields = [field for field in region_fields if field not in region_data]
    if missing_region_fields:
        raise DailyImagePreparationError(
            "snapshot.layout.presentation_region is missing " + ", ".join(missing_region_fields)
        )
    region = PresentationRegion(**{field: region_data[field] for field in region_fields})

    min_font_size = layout.get("min_font_size")
    max_font_size = layout.get("max_font_size")
    if type(min_font_size) is not int or min_font_size <= 0:
        raise DailyImagePreparationError("snapshot.layout.min_font_size must be a positive integer")
    if type(max_font_size) is not int or max_font_size < min_font_size:
        raise DailyImagePreparationError(
            "snapshot.layout.max_font_size must be an integer greater than or equal to min_font_size"
        )

    composition = LiteraryComposition(
        quotation=snapshot.quotation_text,
        source=optional_fields["source"],
        attribution=optional_fields["attribution"],
    )
    return composition, region, (size[0], size[1]), min_font_size, max_font_size, style


def _generate_daily_background(image_size: tuple[int, int]) -> Image.Image:
    return Image.new("RGB", image_size, _BACKGROUND_COLOR)


def prepare_daily_images(
    snapshot: DailySnapshot,
    stages: Sequence[CompositionVisibility],
) -> tuple[Image.Image, ...]:
    """Prepare complete, independent images for explicit cumulative reveal stages.

    All presentation values and font bytes come from ``snapshot``. Stages are
    validated by the shared renderer and are never inferred from the clock.
    """
    if not isinstance(snapshot, DailySnapshot):
        raise DailyImagePreparationError("snapshot must be a DailySnapshot")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")

    composition, region, image_size, min_font_size, max_font_size, style = _resolve_presentation(snapshot)
    try:
        layout = layout_composition(
            composition,
            snapshot.font,
            region,
            image_size,
            min_font_size,
            max_font_size,
            style,
            byline_gap_factor=_BYLINE_GAP_FACTOR,
        )
        background = _generate_daily_background(image_size)
        return render_reveal_stages(
            background,
            snapshot.font,
            layout,
            tuple(stages),
            concealment="pixel-distortion",
        )
    except QuotationRenderError as error:
        raise DailyImagePreparationError(f"cannot prepare daily snapshot images: {error}") from error


__all__ = ["DailyImagePreparationError", "prepare_daily_images"]

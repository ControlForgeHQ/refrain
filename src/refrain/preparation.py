"""Hardware-independent preparation of daily presentation images."""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping, Sequence

from PIL import Image, ImageFont

from .config import (
    BackgroundResource,
    DecorationResource,
    FontResource,
    PresentationRegion,
    load_background_image,
    load_decoration_image,
)
from .persistence import DailySnapshot, ResolvedFont
from .renderer import (
    CompositionVisibility,
    LiteraryComposition,
    QuotationRenderError,
    layout_composition,
    render_reveal_stages,
)

_BACKGROUND_COLOR = "#FFFFFF"
_BYLINE_GAP_FACTOR = 1.20
_LOGGER = logging.getLogger(__name__)


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


def _generate_daily_background(
    image_size: tuple[int, int],
    identifier: str,
    registry: Mapping[str, BackgroundResource],
) -> Image.Image:
    base = Image.new("RGB", image_size, _BACKGROUND_COLOR)
    if identifier == "none":
        return base
    resource = registry.get(identifier)
    if resource is None:
        _LOGGER.warning("Committed background %r is unavailable; using the paper-white base", identifier)
        return base
    try:
        with load_background_image(resource) as image:
            if image.size != image_size:
                raise ValueError("background dimensions do not match the committed image size")
            base.paste(image, (0, 0), image if image.mode == "RGBA" else None)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        _LOGGER.warning(
            "Committed background %r is unavailable or unusable; using the paper-white base: %s",
            identifier,
            error,
        )
    return base


def _apply_daily_decoration(
    background: Image.Image,
    identifier: str,
    registry: Mapping[str, DecorationResource],
) -> Image.Image:
    if identifier == "none":
        return background
    resource = registry.get(identifier)
    if resource is None:
        _LOGGER.warning("Committed decoration %r is unavailable; omitting the overlay", identifier)
        return background
    try:
        with load_decoration_image(resource) as image:
            if image.size != background.size:
                raise ValueError("decoration dimensions do not match the committed image size")
            background.paste(image, (0, 0), image)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        _LOGGER.warning(
            "Committed decoration %r is unavailable or unusable; omitting the overlay: %s",
            identifier,
            error,
        )
    return background


def _read_font(resource: FontResource) -> ResolvedFont:
    with resource.path.open("rb") as font_file:
        font = ResolvedFont(resource.identifier, font_file.read())
    ImageFont.truetype(io.BytesIO(font.data), size=12)
    return font


def _resolve_font(snapshot: DailySnapshot, registry: Mapping[str, FontResource]) -> ResolvedFont:
    selected = registry.get(snapshot.font_identifier)
    if selected is not None:
        try:
            return _read_font(selected)
        except (OSError, ValueError) as error:
            _LOGGER.warning(
                "Committed font %r is unavailable or unusable; using a bundled fallback: %s",
                snapshot.font_identifier,
                error,
            )
    else:
        _LOGGER.warning(
            "Committed font %r is unavailable; using a bundled fallback",
            snapshot.font_identifier,
        )

    for identifier, resource in sorted(registry.items()):
        if not resource.bundled:
            continue
        try:
            return _read_font(resource)
        except (OSError, ValueError) as error:
            _LOGGER.warning("Bundled fallback font %r is unusable: %s", identifier, error)
    raise DailyImagePreparationError(
        f"cannot prepare daily snapshot: committed font {snapshot.font_identifier!r} is unavailable or unusable "
        "and no usable bundled fallback font is registered"
    )


def prepare_daily_images(
    snapshot: DailySnapshot,
    stages: Sequence[CompositionVisibility],
    font_registry: Mapping[str, FontResource],
    background_registry: Mapping[str, BackgroundResource] | None = None,
    decoration_registry: Mapping[str, DecorationResource] | None = None,
) -> tuple[Image.Image, ...]:
    """Prepare complete, independent images for explicit cumulative reveal stages.

    Presentation values come from ``snapshot``; its font identifier is resolved
    through the effective registry. Stages are validated by the shared renderer
    and are never inferred from the clock. A background registry is required
    unless the committed background identifier is ``"none"``.
    """
    if not isinstance(snapshot, DailySnapshot):
        raise DailyImagePreparationError("snapshot must be a DailySnapshot")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if not isinstance(font_registry, Mapping):
        raise DailyImagePreparationError("font_registry must be a mapping of font identifiers to font resources")
    if background_registry is None and snapshot.background_identifier != "none":
        raise DailyImagePreparationError(
            "background_registry must be supplied when the committed background identifier is not 'none'"
        )
    if background_registry is not None and not isinstance(background_registry, Mapping):
        raise DailyImagePreparationError("background_registry must be a mapping of identifiers to background resources")
    if decoration_registry is not None and not isinstance(decoration_registry, Mapping):
        raise DailyImagePreparationError("decoration_registry must be a mapping of identifiers to decoration resources")

    composition, region, image_size, min_font_size, max_font_size, style = _resolve_presentation(snapshot)
    font = _resolve_font(snapshot, font_registry)
    try:
        layout = layout_composition(
            composition,
            font,
            region,
            image_size,
            min_font_size,
            max_font_size,
            style,
            byline_gap_factor=_BYLINE_GAP_FACTOR,
        )
        background = _generate_daily_background(
            image_size, snapshot.background_identifier, {} if background_registry is None else background_registry
        )
        background = _apply_daily_decoration(
            background,
            snapshot.decoration_identifier,
            {} if decoration_registry is None else decoration_registry,
        )
        try:
            return render_reveal_stages(
                background,
                font,
                layout,
                tuple(stages),
                concealment="pixel-distortion",
            )
        finally:
            background.close()
    except QuotationRenderError as error:
        raise DailyImagePreparationError(f"cannot prepare daily snapshot images: {error}") from error


__all__ = ["DailyImagePreparationError", "prepare_daily_images"]

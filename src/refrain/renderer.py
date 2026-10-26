"""Hardware-independent literary composition layout and Pillow rendering."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from PIL import Image, ImageDraw, ImageFont

PixelBounds = tuple[int, int, int, int]
PixelPosition = tuple[int, int]
PresentationStyle = Literal["centered", "prose"]


class PresentationRegion(Protocol):
    """Normalized presentation rectangle supplied by the caller."""

    x: float
    y: float
    width: float
    height: float


class ResolvedFontData(Protocol):
    """Resolved Pillow font bytes supplied independently of font selection."""

    identifier: str
    data: bytes


class QuotationRenderError(ValueError):
    """Raised when a literary composition cannot be laid out or rendered."""


@dataclass(frozen=True)
class LiteraryComposition:
    """Resolved quotation content and its optional source and attribution."""

    quotation: str
    source: str | None = None
    attribution: str | None = None


@dataclass(frozen=True)
class CompositionVisibility:
    """Cumulative visibility of fields for one prepared reveal image."""

    quotation: bool = True
    source: bool = False
    attribution: bool = False


@dataclass(frozen=True)
class TextFieldLayout:
    """Resolved typography and pixel placement for one composition field."""

    text: str
    font_size: int
    lines: tuple[str, ...]
    positions: tuple[PixelPosition, ...]
    bounds: PixelBounds


@dataclass(frozen=True)
class CompositionLayout:
    """Resolved geometry for every present composition field."""

    composition: LiteraryComposition
    font_identifier: str
    font_sha256: str
    image_size: tuple[int, int]
    region: PixelBounds
    style: PresentationStyle
    quotation: TextFieldLayout
    source: TextFieldLayout | None
    attribution: TextFieldLayout | None


@dataclass(frozen=True)
class _MeasuredField:
    text: str
    font_size: int
    lines: tuple[str, ...]
    line_boxes: tuple[tuple[int, int, int, int], ...]
    gaps: tuple[int, ...]
    line_height: int
    height: int


def _validate_region(region: PresentationRegion) -> None:
    try:
        values = (region.x, region.y, region.width, region.height)
    except AttributeError as error:
        raise QuotationRenderError("presentation_region must provide x, y, width, and height") from error
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values
    ):
        raise QuotationRenderError("presentation_region coordinates must be finite numbers")
    if (
        region.x < 0
        or region.y < 0
        or region.width <= 0
        or region.height <= 0
        or region.x + region.width > 1
        or region.y + region.height > 1
    ):
        raise QuotationRenderError("presentation_region must be a positive normalized rectangle inside the image")


def _validate_sizes(min_font_size: int, max_font_size: int) -> None:
    if isinstance(min_font_size, bool) or not isinstance(min_font_size, int) or min_font_size <= 0:
        raise QuotationRenderError("min_font_size must be a positive integer")
    if isinstance(max_font_size, bool) or not isinstance(max_font_size, int) or max_font_size <= 0:
        raise QuotationRenderError("max_font_size must be a positive integer")
    if max_font_size < min_font_size:
        raise QuotationRenderError("max_font_size must be greater than or equal to min_font_size")


def _validate_composition(composition: LiteraryComposition) -> None:
    if not isinstance(composition, LiteraryComposition):
        raise QuotationRenderError("composition must be a LiteraryComposition")
    for field_name in ("quotation", "source", "attribution"):
        value = getattr(composition, field_name)
        if field_name == "quotation":
            if not isinstance(value, str) or not value.strip():
                raise QuotationRenderError("quotation must be a nonempty string")
        elif value is not None and (not isinstance(value, str) or not value.strip()):
            raise QuotationRenderError(f"{field_name} must be a nonempty string when supplied")


def _validate_font(font: ResolvedFontData) -> None:
    if (
        not isinstance(getattr(font, "identifier", None), str)
        or not font.identifier
        or not isinstance(getattr(font, "data", None), bytes)
        or not font.data
    ):
        raise QuotationRenderError("font must provide a nonempty identifier and resolved font bytes")


def _font_sha256(font: ResolvedFontData) -> str:
    return hashlib.sha256(font.data).hexdigest()


def _load_font(font: ResolvedFontData, size: int) -> ImageFont.FreeTypeFont:
    _validate_font(font)
    try:
        return ImageFont.truetype(io.BytesIO(font.data), size=size)
    except (OSError, ValueError) as error:
        raise QuotationRenderError(f"resolved font {font.identifier!r} cannot be loaded by Pillow: {error}") from error


def _text_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    if not text:
        return 0
    left, _, right, _ = font.getbbox(text)
    return max(font.getlength(text), right - left)


def _wrap_segment(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    if not text:
        return [""]

    lines: list[str] = []
    line = ""
    pending_whitespace = ""
    for token in re.findall(r"\s+|\S+", text):
        if token.isspace():
            if line:
                pending_whitespace += token
            else:
                line += token
            continue

        candidate = line + pending_whitespace + token
        if line and _text_width(font, candidate) > width:
            lines.append(line)
            line = token
        else:
            line = candidate
        pending_whitespace = ""
    if pending_whitespace:
        line += pending_whitespace
    if line:
        lines.append(line)
    return lines or [""]


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, width: int) -> tuple[tuple[str, ...], tuple[bool, ...]]:
    segments = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    paragraph_breaks: list[bool] = []
    for index, segment in enumerate(segments):
        wrapped = _wrap_segment(segment, font, width)
        lines.extend(wrapped)
        paragraph_breaks.extend([False] * (len(wrapped) - 1))
        if index < len(segments) - 1:
            paragraph_breaks.append(not segment or not segments[index + 1])
    return tuple(lines), tuple(paragraph_breaks)


def _measure_field(
    text: str,
    font: ResolvedFontData,
    font_size: int,
    width: int,
) -> _MeasuredField | None:
    pillow_font = _load_font(font, font_size)
    lines, paragraph_breaks = _wrap_text(text, pillow_font, width)
    ascent, descent = pillow_font.getmetrics()
    line_height = max(1, ascent + descent)
    line_gap = max(1, round(font_size * 0.28))
    paragraph_gap = max(line_gap, round(font_size * 0.72))
    gaps = tuple(paragraph_gap if is_paragraph else line_gap for is_paragraph in paragraph_breaks)

    line_boxes: list[tuple[int, int, int, int]] = []
    for line in lines:
        if line:
            left, top, right, bottom = pillow_font.getbbox(line)
            if max(pillow_font.getlength(line), right - left) > width:
                return None
            line_boxes.append((left, top, right, bottom))
        else:
            line_boxes.append((0, 0, 0, 0))
    height = len(lines) * line_height + sum(gaps)
    return _MeasuredField(text, font_size, lines, tuple(line_boxes), gaps, line_height, height)


def _centered_line_lefts(field: _MeasuredField, region_width: int) -> tuple[int, ...]:
    return tuple((region_width - (box[2] - box[0])) // 2 for box in field.line_boxes)


def _prose_line_lefts(field: _MeasuredField, region_width: int) -> tuple[int, ...]:
    widest_line = max(box[2] - box[0] for line, box in zip(field.lines, field.line_boxes, strict=True))
    block_left = (region_width - widest_line) // 2
    return (block_left,) * len(field.lines)


_STYLE_LAYOUTS = {
    "centered": _centered_line_lefts,
    "prose": _prose_line_lefts,
}

LineAlignment = Callable[[_MeasuredField, int], tuple[int, ...]]


def _place_field(
    field: _MeasuredField,
    left: int,
    top: int,
    region_width: int,
    align_lines: LineAlignment,
) -> TextFieldLayout:
    line_lefts = align_lines(field, region_width)
    positions: list[PixelPosition] = []
    visible_boxes: list[PixelBounds] = []
    y = top
    for index, (line, box, line_left) in enumerate(zip(field.lines, field.line_boxes, line_lefts, strict=True)):
        glyph_left, glyph_top, glyph_right, glyph_bottom = box
        if line:
            ink_left = left + line_left
            ink_top = y + (field.line_height - (glyph_bottom - glyph_top)) // 2
            positions.append((ink_left - glyph_left, ink_top - glyph_top))
            visible_boxes.append(
                (ink_left, ink_top, ink_left + glyph_right - glyph_left, ink_top + glyph_bottom - glyph_top)
            )
        else:
            positions.append((left + line_left, y))
        if index < len(field.lines) - 1:
            y += field.line_height + field.gaps[index]
    if not visible_boxes:
        return TextFieldLayout(field.text, field.font_size, field.lines, tuple(positions), (left, top, left, top))
    bounds = (
        min(box[0] for box in visible_boxes),
        min(box[1] for box in visible_boxes),
        max(box[2] for box in visible_boxes),
        max(box[3] for box in visible_boxes),
    )
    return TextFieldLayout(field.text, field.font_size, field.lines, tuple(positions), bounds)


def _layout_at_size(
    composition: LiteraryComposition,
    font: ResolvedFontData,
    image_size: tuple[int, int],
    region: PixelBounds,
    quote_size: int,
    style: PresentationStyle,
) -> CompositionLayout | None:
    left, top, right, bottom = region
    region_width, region_height = right - left, bottom - top
    quote = _measure_field(composition.quotation, font, quote_size, region_width)
    source = (
        _measure_field(composition.source, font, max(1, round(quote_size * 0.48)), region_width)
        if composition.source is not None
        else None
    )
    attribution = (
        _measure_field(composition.attribution, font, max(1, round(quote_size * 0.42)), region_width)
        if composition.attribution is not None
        else None
    )
    if quote is None or (composition.source is not None and source is None):
        return None
    if composition.attribution is not None and attribution is None:
        return None

    if quote_size == 1 and (source is not None or attribution is not None):
        return None
    field_gap = max(1, round(quote_size * 0.55))
    metadata = [field for field in (source, attribution) if field is not None]
    metadata_height = sum(field.height for field in metadata) + field_gap * max(0, len(metadata) - 1)
    quotation_area_height = region_height - metadata_height - (field_gap if metadata else 0)
    if quote.height > quotation_area_height:
        return None

    align = _STYLE_LAYOUTS[style]
    quote_y = top + (quotation_area_height - quote.height) // 2
    quote_layout = _place_field(quote, left, quote_y, region_width, align)
    y = top + quotation_area_height + (field_gap if metadata else 0)
    if source is not None:
        source_layout = _place_field(source, left, y, region_width, _centered_line_lefts)
        y += source.height + (field_gap if attribution is not None else 0)
    else:
        source_layout = None
    if attribution is not None:
        attribution_layout = _place_field(attribution, left, y, region_width, _centered_line_lefts)
    else:
        attribution_layout = None

    return CompositionLayout(
        composition=composition,
        font_identifier=font.identifier,
        font_sha256=_font_sha256(font),
        image_size=image_size,
        region=region,
        style=style,
        quotation=quote_layout,
        source=source_layout,
        attribution=attribution_layout,
    )


def layout_composition(
    composition: LiteraryComposition,
    font: ResolvedFontData,
    presentation_region: PresentationRegion,
    image_size: tuple[int, int],
    min_font_size: int,
    max_font_size: int,
    presentation_style: PresentationStyle,
) -> CompositionLayout:
    """Fit the complete literary composition once for reuse across reveal images."""
    _validate_composition(composition)
    if not isinstance(image_size, tuple) or len(image_size) != 2:
        raise QuotationRenderError("image_size must be a (width, height) tuple")
    width, height = image_size
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in image_size):
        raise QuotationRenderError("image dimensions must be positive integers")
    _validate_region(presentation_region)
    _validate_sizes(min_font_size, max_font_size)
    if not isinstance(presentation_style, str) or presentation_style not in _STYLE_LAYOUTS:
        raise QuotationRenderError("presentation_style must be 'centered' or 'prose'")
    _validate_font(font)
    pixel_region = (
        math.floor(presentation_region.x * width),
        math.floor(presentation_region.y * height),
        math.ceil((presentation_region.x + presentation_region.width) * width),
        math.ceil((presentation_region.y + presentation_region.height) * height),
    )
    if pixel_region[2] <= pixel_region[0] or pixel_region[3] <= pixel_region[1]:
        raise QuotationRenderError("presentation_region is smaller than one pixel at the supplied image dimensions")

    low, high = min_font_size, max_font_size
    best = _layout_at_size(composition, font, image_size, pixel_region, min_font_size, presentation_style)
    if best is None:
        raise QuotationRenderError(
            f"literary composition does not fit within region {pixel_region} at "
            f"the minimum quotation font size {min_font_size}"
        )
    while low <= high:
        size = (low + high) // 2
        candidate = _layout_at_size(composition, font, image_size, pixel_region, size, presentation_style)
        if candidate is None:
            high = size - 1
        else:
            best = candidate
            low = size + 1
    return best


def _draw_field(
    draw: ImageDraw.ImageDraw,
    font: ResolvedFontData,
    field: TextFieldLayout,
    color: tuple[int, ...] | int,
) -> None:
    pillow_font = _load_font(font, field.font_size)
    for line, position in zip(field.lines, field.positions, strict=True):
        if line:
            draw.text(position, line, font=pillow_font, fill=color)


def render_reveal_stages(
    background: Image.Image,
    font: ResolvedFontData,
    layout: CompositionLayout,
    stages: Sequence[CompositionVisibility],
) -> tuple[Image.Image, ...]:
    """Render requested cumulative visibility stages from one resolved layout."""
    if not isinstance(background, Image.Image):
        raise QuotationRenderError("background must be a Pillow image")
    if background.mode not in {"1", "L", "RGB", "RGBA"}:
        raise QuotationRenderError(f"background image mode {background.mode!r} is not supported")
    if not isinstance(layout, CompositionLayout):
        raise QuotationRenderError("layout must be a CompositionLayout")
    if background.size != layout.image_size:
        raise QuotationRenderError("background dimensions do not match the composition layout")
    _validate_font(font)
    if font.identifier != layout.font_identifier or _font_sha256(font) != layout.font_sha256:
        raise QuotationRenderError("font does not match the resolved font used to create the composition layout")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise QuotationRenderError("stages must be a nonempty sequence of CompositionVisibility values")

    previous = CompositionVisibility(quotation=False)
    for stage in stages:
        if not isinstance(stage, CompositionVisibility) or any(
            not isinstance(value, bool) for value in (stage.quotation, stage.source, stage.attribution)
        ):
            raise QuotationRenderError("each stage must be a CompositionVisibility value")
        if not stage.quotation:
            raise QuotationRenderError("the quotation must be visible in every stage")
        if (stage.source and layout.source is None) or (stage.attribution and layout.attribution is None):
            raise QuotationRenderError("a stage cannot reveal a field that is absent from the composition")
        if (previous.source and not stage.source) or (previous.attribution and not stage.attribution):
            raise QuotationRenderError("reveal stages must be cumulative")
        previous = stage

    fill: tuple[int, ...] | int
    fill = (0, 0, 0, 255) if background.mode == "RGBA" else ((0, 0, 0) if background.mode == "RGB" else 0)
    rendered: list[Image.Image] = []
    for stage in stages:
        image = background.copy()
        draw = ImageDraw.Draw(image)
        _draw_field(draw, font, layout.quotation, fill)
        if stage.source and layout.source is not None:
            _draw_field(draw, font, layout.source, fill)
        if stage.attribution and layout.attribution is not None:
            _draw_field(draw, font, layout.attribution, fill)
        rendered.append(image)
    return tuple(rendered)


__all__ = [
    "CompositionLayout",
    "CompositionVisibility",
    "LiteraryComposition",
    "PresentationRegion",
    "PresentationStyle",
    "QuotationRenderError",
    "ResolvedFontData",
    "TextFieldLayout",
    "layout_composition",
    "render_reveal_stages",
]

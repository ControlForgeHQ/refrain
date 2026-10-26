"""Hardware-independent literary composition layout and Pillow rendering."""

from __future__ import annotations

import hashlib
import io
import math
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
class BylineLayout:
    """Resolved unified attribution/source row and persistent punctuation."""

    attribution: TextFieldLayout | None
    source: TextFieldLayout | None
    prefix: TextFieldLayout | None
    separator: TextFieldLayout | None
    bounds: PixelBounds


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
    byline_gap: int
    quotation: TextFieldLayout
    byline: BylineLayout | None


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


def _text_field(
    text: str,
    font: ImageFont.FreeTypeFont,
    position: PixelPosition,
) -> TextFieldLayout:
    x, y = round(position[0]), round(position[1])
    left, top, right, bottom = font.getbbox(text)
    bounds = (
        x + left,
        y + top,
        x + right,
        y + bottom,
    )
    return TextFieldLayout(text, font.size, (text,), ((x, y),), bounds)


def _layout_byline(
    composition: LiteraryComposition,
    font: ResolvedFontData,
    quote_size: int,
    region: PixelBounds,
    style: PresentationStyle,
) -> BylineLayout | None:
    if composition.source is None and composition.attribution is None:
        return None

    left, top, right, bottom = region
    region_width = right - left
    byline_size = min(round(quote_size * 0.42), quote_size - 1)
    prefix_text = "— "
    separator_text = ", " if composition.attribution is not None and composition.source is not None else ""

    while byline_size > 0:
        pillow_font = _load_font(font, byline_size)
        prefix_advance = pillow_font.getlength(prefix_text)
        attribution_advance = pillow_font.getlength(composition.attribution) if composition.attribution else 0
        separator_advance = pillow_font.getlength(separator_text) if separator_text else 0
        field_metrics = []
        if composition.attribution is not None:
            field_metrics.append(pillow_font.getbbox(composition.attribution))
        if composition.source is not None:
            field_metrics.append(pillow_font.getbbox(composition.source))
        field_metrics.append(pillow_font.getbbox(prefix_text))
        if separator_text:
            field_metrics.append(pillow_font.getbbox(separator_text))
        text_top = min(bounds[1] for bounds in field_metrics)
        text_bottom = max(bounds[3] for bounds in field_metrics)
        byline_top = bottom - (text_bottom - text_top)
        if byline_top < top:
            byline_size -= 1
            continue

        y = byline_top - text_top
        prefix = _text_field(prefix_text, pillow_font, (left, y))
        x = round(left + prefix_advance)

        def place_after(text: str, position_x: int, previous: TextFieldLayout) -> TextFieldLayout:
            field = _text_field(text, pillow_font, (position_x, y))
            if field.bounds[0] < previous.bounds[2]:
                position_x += previous.bounds[2] - field.bounds[0]
                field = _text_field(text, pillow_font, (position_x, y))
            return field

        attribution_layout = None
        if composition.attribution is not None:
            attribution_layout = place_after(composition.attribution, x, prefix)
            x = round(attribution_layout.positions[0][0] + attribution_advance)
        separator = None
        previous = attribution_layout or prefix
        if separator_text:
            separator = place_after(separator_text, x, previous)
            x = round(separator.positions[0][0] + separator_advance)
            previous = separator
        source_layout = place_after(composition.source, x, previous) if composition.source is not None else None

        field_layouts = [field for field in (prefix, attribution_layout, separator, source_layout) if field is not None]
        bounds = (
            min(field.bounds[0] for field in field_layouts),
            min(field.bounds[1] for field in field_layouts),
            max(field.bounds[2] for field in field_layouts),
            max(field.bounds[3] for field in field_layouts),
        )
        if bounds[2] - bounds[0] > region_width:
            byline_size -= 1
            continue
        target_left = (
            left + (region_width - (bounds[2] - bounds[0])) // 2
            if style == "centered"
            else right - (bounds[2] - bounds[0])
        )
        shift_x = target_left - bounds[0]

        def shifted(field: TextFieldLayout | None) -> TextFieldLayout | None:
            if field is None:
                return None
            return TextFieldLayout(
                field.text,
                field.font_size,
                field.lines,
                tuple((position[0] + shift_x, position[1]) for position in field.positions),
                (field.bounds[0] + shift_x, field.bounds[1], field.bounds[2] + shift_x, field.bounds[3]),
            )

        byline = BylineLayout(
            shifted(attribution_layout),
            shifted(source_layout),
            shifted(prefix),
            shifted(separator),
            (target_left, bounds[1], target_left + bounds[2] - bounds[0], bounds[3]),
        )
        if byline.bounds[0] < left or byline.bounds[1] < top or byline.bounds[2] > right or byline.bounds[3] > bottom:
            byline_size -= 1
            continue
        return byline
    return None


def _shift_field_y(field: TextFieldLayout, amount: int) -> TextFieldLayout:
    return TextFieldLayout(
        field.text,
        field.font_size,
        field.lines,
        tuple((position[0], position[1] + amount) for position in field.positions),
        (field.bounds[0], field.bounds[1] + amount, field.bounds[2], field.bounds[3] + amount),
    )


def _shift_byline_y(byline: BylineLayout, amount: int) -> BylineLayout:
    def shifted(field: TextFieldLayout | None) -> TextFieldLayout | None:
        return _shift_field_y(field, amount) if field is not None else None

    return BylineLayout(
        shifted(byline.attribution),
        shifted(byline.source),
        shifted(byline.prefix),
        shifted(byline.separator),
        (byline.bounds[0], byline.bounds[1] + amount, byline.bounds[2], byline.bounds[3] + amount),
    )


def _layout_at_size(
    composition: LiteraryComposition,
    font: ResolvedFontData,
    image_size: tuple[int, int],
    region: PixelBounds,
    quote_size: int,
    style: PresentationStyle,
    byline_gap_factor: float,
) -> CompositionLayout | None:
    left, top, right, bottom = region
    region_width, region_height = right - left, bottom - top
    quote = _measure_field(composition.quotation, font, quote_size, region_width)
    byline = _layout_byline(composition, font, quote_size, region, style)
    if quote is None or ((composition.source is not None or composition.attribution is not None) and byline is None):
        return None
    align = _STYLE_LAYOUTS[style]
    quote_layout = _place_field(quote, left, 0, region_width, align)
    quotation_height = quote_layout.bounds[3] - quote_layout.bounds[1]
    byline_height = byline.bounds[3] - byline.bounds[1] if byline is not None else 0
    byline_font_size = (
        byline.attribution.font_size if byline and byline.attribution else byline.source.font_size if byline else 0
    )
    byline_line_height = sum(_load_font(font, byline_font_size).getmetrics()) if byline is not None else 0
    field_gap = max(0, round(quote_size * byline_gap_factor)) if byline is not None else 0
    metrics_height = quote.height + field_gap + byline_line_height
    if metrics_height > region_height:
        return None

    composition_height = quotation_height + field_gap + byline_height
    composition_top = top + (region_height - composition_height) // 2
    quote_layout = _place_field(quote, left, composition_top - quote_layout.bounds[1], region_width, align)
    if byline is not None:
        target_byline_top = composition_top + quotation_height + field_gap
        byline = _shift_byline_y(byline, target_byline_top - byline.bounds[1])

    return CompositionLayout(
        composition=composition,
        font_identifier=font.identifier,
        font_sha256=_font_sha256(font),
        image_size=image_size,
        region=region,
        style=style,
        byline_gap=field_gap,
        quotation=quote_layout,
        byline=byline,
    )


def layout_composition(
    composition: LiteraryComposition,
    font: ResolvedFontData,
    presentation_region: PresentationRegion,
    image_size: tuple[int, int],
    min_font_size: int,
    max_font_size: int,
    presentation_style: PresentationStyle,
    *,
    byline_gap_factor: float = 1.20,
) -> CompositionLayout:
    """Fit the complete literary composition once for reuse across reveal images."""
    _validate_composition(composition)
    if (
        isinstance(byline_gap_factor, bool)
        or not isinstance(byline_gap_factor, (int, float))
        or not math.isfinite(byline_gap_factor)
        or byline_gap_factor < 0
    ):
        raise QuotationRenderError("byline_gap_factor must be a finite nonnegative number")
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
    best = _layout_at_size(
        composition,
        font,
        image_size,
        pixel_region,
        min_font_size,
        presentation_style,
        byline_gap_factor,
    )
    if best is None:
        raise QuotationRenderError(
            f"literary composition does not fit within region {pixel_region} at "
            f"the minimum quotation font size {min_font_size}"
        )
    while low <= high:
        size = (low + high) // 2
        candidate = _layout_at_size(
            composition,
            font,
            image_size,
            pixel_region,
            size,
            presentation_style,
            byline_gap_factor,
        )
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


def _conceal_field(
    image: Image.Image,
    font: ResolvedFontData,
    field: TextFieldLayout,
) -> None:
    left, top, right, bottom = field.bounds
    width, height = right - left, bottom - top
    cell_size = max(2, field.font_size // 6)
    coarse_size = (max(1, math.ceil(width / cell_size)), max(1, math.ceil(height / cell_size)))
    glyphs = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(glyphs)
    pillow_font = _load_font(font, field.font_size)
    for line, position in zip(field.lines, field.positions, strict=True):
        if line:
            draw.text((position[0] - left, position[1] - top), line, font=pillow_font, fill=255)
    coarse_glyphs = glyphs.resize(coarse_size, Image.Resampling.BOX)
    neighborhood = coarse_glyphs.filter(ImageFilter.GaussianBlur(radius=1.15))
    seed = int.from_bytes(hashlib.sha256(f"{font.identifier}\0{field.text}".encode()).digest(), "big")
    randomizer = random.Random(seed)
    alpha = Image.new("L", coarse_size)
    garbled_cells = []
    for density in neighborhood.get_flattened_data():
        occupancy = min(0.56, 0.08 + density / 255 * 0.48)
        garbled_cells.append(randomizer.randint(112, 232) if randomizer.random() < occupancy else 0)
    alpha.putdata(garbled_cells)
    alpha = alpha.resize((width, height), Image.Resampling.NEAREST)

    crop = image.crop((left, top, right, bottom))
    if image.mode == "1":
        base = crop.convert("L")
        concealed = Image.composite(Image.new("L", crop.size, 128), base, alpha)
        image.paste(concealed.convert("1", dither=Image.Dither.FLOYDSTEINBERG), (left, top))
    elif image.mode == "L":
        concealed = Image.composite(Image.new("L", crop.size, 64), crop, alpha)
        image.paste(concealed, (left, top))
    else:
        base = crop.convert("RGB")
        concealed = Image.composite(Image.new("RGB", crop.size, (64, 64, 64)), base, alpha)
        if image.mode == "RGBA":
            concealed.putalpha(crop.getchannel("A"))
        image.paste(concealed, (left, top))


def _attribution_color(mode: str) -> tuple[int, ...] | int:
    if mode == "1":
        return 0
    if mode == "L":
        return 48
    if mode == "RGBA":
        return (48, 48, 48, 255)
    return (48, 48, 48)


def render_reveal_stages(
    background: Image.Image,
    font: ResolvedFontData,
    layout: CompositionLayout,
    stages: Sequence[CompositionVisibility],
    *,
    concealment: Literal["pixel-distortion"] = "pixel-distortion",
) -> tuple[Image.Image, ...]:
    """Render requested cumulative visibility stages from one resolved layout."""
    if concealment != "pixel-distortion":
        raise QuotationRenderError("concealment must be 'pixel-distortion'")
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
        if (stage.source and (layout.byline is None or layout.byline.source is None)) or (
            stage.attribution and (layout.byline is None or layout.byline.attribution is None)
        ):
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
        byline = layout.byline
        if byline is not None:
            if byline.attribution is not None:
                if not stage.attribution:
                    _conceal_field(image, font, byline.attribution)
                else:
                    _draw_field(draw, font, byline.attribution, _attribution_color(image.mode))
            if byline.source is not None:
                if not stage.source:
                    _conceal_field(image, font, byline.source)
                else:
                    _draw_field(draw, font, byline.source, fill)
            punctuation = ImageDraw.Draw(image)
            if byline.prefix is not None:
                _draw_field(punctuation, font, byline.prefix, fill)
            if byline.separator is not None:
                _draw_field(punctuation, font, byline.separator, fill)
        rendered.append(image)
    return tuple(rendered)


__all__ = [
    "CompositionLayout",
    "CompositionVisibility",
    "BylineLayout",
    "LiteraryComposition",
    "PresentationRegion",
    "PresentationStyle",
    "QuotationRenderError",
    "ResolvedFontData",
    "TextFieldLayout",
    "layout_composition",
    "render_reveal_stages",
]

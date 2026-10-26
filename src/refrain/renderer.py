"""Hardware-independent quotation layout and Pillow rendering."""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import TypeAlias

from PIL import Image, ImageDraw, ImageFont

from .config import QuotationRegion
from .persistence import ResolvedFont

PixelBounds: TypeAlias = tuple[int, int, int, int]
PixelPosition: TypeAlias = tuple[int, int]


class QuotationRenderError(ValueError):
    """Raised when a quotation cannot be laid out or rendered as requested."""


@dataclass(frozen=True)
class QuotationLayout:
    """A deterministic quotation layout reusable on same-sized backgrounds."""

    text: str
    font_identifier: str
    font_sha256: str
    image_size: tuple[int, int]
    region: PixelBounds
    font_size: int
    lines: tuple[str, ...]
    positions: tuple[PixelPosition, ...]
    text_bounds: PixelBounds


def _validate_region(region: QuotationRegion) -> None:
    if not isinstance(region, QuotationRegion):
        raise QuotationRenderError("region must be a QuotationRegion")
    values = (region.x, region.y, region.width, region.height)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values
    ):
        raise QuotationRenderError("region coordinates must be finite numbers")
    if (
        region.x < 0
        or region.y < 0
        or region.width <= 0
        or region.height <= 0
        or region.x + region.width > 1
        or region.y + region.height > 1
    ):
        raise QuotationRenderError("region must be a positive normalized rectangle inside the image")


def _validate_sizes(min_font_size: int, max_font_size: int) -> None:
    if isinstance(min_font_size, bool) or not isinstance(min_font_size, int) or min_font_size <= 0:
        raise QuotationRenderError("min_font_size must be a positive integer")
    if isinstance(max_font_size, bool) or not isinstance(max_font_size, int) or max_font_size <= 0:
        raise QuotationRenderError("max_font_size must be a positive integer")
    if max_font_size < min_font_size:
        raise QuotationRenderError("max_font_size must be greater than or equal to min_font_size")


def _load_font(font: ResolvedFont, size: int) -> ImageFont.FreeTypeFont:
    if not isinstance(font, ResolvedFont):
        raise QuotationRenderError("font must be a ResolvedFont")
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
    paragraph_gaps: list[bool] = []
    for segment_index, segment in enumerate(segments):
        wrapped = _wrap_segment(segment, font, width)
        lines.extend(wrapped)
        paragraph_gaps.extend([False] * (len(wrapped) - 1))
        if segment_index < len(segments) - 1:
            paragraph_gaps.append(not segment or not segments[segment_index + 1])
    return tuple(lines), tuple(paragraph_gaps)


def _layout_at_size(
    text: str,
    font: ResolvedFont,
    image_size: tuple[int, int],
    region: PixelBounds,
    font_size: int,
) -> QuotationLayout | None:
    left, top, right, bottom = region
    region_width = right - left
    region_height = bottom - top
    pillow_font = _load_font(font, font_size)
    lines, paragraph_gaps = _wrap_text(text, pillow_font, region_width)
    ascent, descent = pillow_font.getmetrics()
    line_height = max(1, ascent + descent)
    line_gap = max(1, round(font_size * 0.28))
    paragraph_gap = max(line_gap, round(font_size * 0.72))
    gaps = tuple(paragraph_gap if is_paragraph else line_gap for is_paragraph in paragraph_gaps)
    block_height = len(lines) * line_height + sum(gaps)
    if block_height > region_height:
        return None

    line_boxes: list[tuple[int, int, int, int]] = []
    positions: list[PixelPosition] = []
    y = top + (region_height - block_height) // 2
    for index, line in enumerate(lines):
        if line:
            glyph_left, glyph_top, glyph_right, glyph_bottom = pillow_font.getbbox(line)
            glyph_width = glyph_right - glyph_left
            glyph_height = glyph_bottom - glyph_top
            if glyph_width > region_width:
                return None
            ink_left = left + (region_width - glyph_width) // 2
            ink_top = y + (line_height - glyph_height) // 2
            position = (ink_left - glyph_left, ink_top - glyph_top)
            line_boxes.append((ink_left, ink_top, ink_left + glyph_width, ink_top + glyph_height))
        else:
            position = (left, y)
        positions.append(position)
        if index < len(lines) - 1:
            y += line_height + gaps[index]
    if not line_boxes:
        return None

    text_bounds = (
        min(box[0] for box in line_boxes),
        min(box[1] for box in line_boxes),
        max(box[2] for box in line_boxes),
        max(box[3] for box in line_boxes),
    )
    return QuotationLayout(
        text=text,
        font_identifier=font.identifier,
        font_sha256=font.sha256,
        image_size=image_size,
        region=region,
        font_size=font_size,
        lines=lines,
        positions=tuple(positions),
        text_bounds=text_bounds,
    )


def layout_quotation(
    text: str,
    font: ResolvedFont,
    region: QuotationRegion,
    image_size: tuple[int, int],
    min_font_size: int,
    max_font_size: int,
) -> QuotationLayout:
    """Fit and position quotation text without depending on a background image."""
    if not isinstance(text, str) or not text.strip():
        raise QuotationRenderError("text must be a nonempty string")
    if not isinstance(image_size, tuple) or len(image_size) != 2:
        raise QuotationRenderError("image_size must be a (width, height) tuple")
    width, height = image_size
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in image_size):
        raise QuotationRenderError("image dimensions must be positive integers")
    _validate_region(region)
    _validate_sizes(min_font_size, max_font_size)
    pixel_region = (
        math.floor(region.x * width),
        math.floor(region.y * height),
        math.ceil((region.x + region.width) * width),
        math.ceil((region.y + region.height) * height),
    )
    if pixel_region[2] <= pixel_region[0] or pixel_region[3] <= pixel_region[1]:
        raise QuotationRenderError("region is smaller than one pixel at the supplied image dimensions")

    minimum_layout = _layout_at_size(text, font, image_size, pixel_region, min_font_size)
    if minimum_layout is None:
        raise QuotationRenderError(
            f"quotation does not fit within region {pixel_region} at the minimum font size {min_font_size}"
        )

    low, high = min_font_size, max_font_size
    best = minimum_layout
    while low <= high:
        size = (low + high) // 2
        layout = _layout_at_size(text, font, image_size, pixel_region, size)
        if layout is None:
            high = size - 1
        else:
            best = layout
            low = size + 1
    return best


def render_quotation(background: Image.Image, font: ResolvedFont, layout: QuotationLayout) -> Image.Image:
    """Return a copy of ``background`` with a previously fitted quotation drawn on it."""
    if not isinstance(background, Image.Image):
        raise QuotationRenderError("background must be a Pillow image")
    if background.mode not in {"1", "L", "RGB", "RGBA"}:
        raise QuotationRenderError(f"background image mode {background.mode!r} is not supported")
    if not isinstance(layout, QuotationLayout):
        raise QuotationRenderError("layout must be a QuotationLayout")
    if background.size != layout.image_size:
        raise QuotationRenderError("background dimensions do not match the quotation layout")
    if not isinstance(font, ResolvedFont):
        raise QuotationRenderError("font must be a ResolvedFont")
    if font.identifier != layout.font_identifier or font.sha256 != layout.font_sha256:
        raise QuotationRenderError("font does not match the resolved font used to create the quotation layout")

    output = background.copy()
    draw = ImageDraw.Draw(output)
    fill = (0, 0, 0, 255) if output.mode == "RGBA" else ((0, 0, 0) if output.mode == "RGB" else 0)
    pillow_font = _load_font(font, layout.font_size)
    for line, position in zip(layout.lines, layout.positions, strict=True):
        if line:
            draw.text(position, line, font=pillow_font, fill=fill)
    return output


__all__ = ["QuotationLayout", "QuotationRenderError", "layout_quotation", "render_quotation"]

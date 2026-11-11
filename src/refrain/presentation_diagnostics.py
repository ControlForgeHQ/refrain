"""Shared presentation-canvas diagnostic overlays."""

from __future__ import annotations

import colorsys
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from .geometry import PixelBounds, round_half_up
from .renderer import annotate_literary_region

if TYPE_CHECKING:
    from .preparation import PreparationDiagnostics

_QR_COLOR = "#FF00FF"


def guide_color(index: int, count: int) -> str:
    """Return a distinct diagnostic color for a group of nine-slice guides."""
    red, green, blue = colorsys.hsv_to_rgb(index / max(count, 1), 0.9, 1)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def guide_groups(details: PreparationDiagnostics) -> dict[tuple[tuple[int, ...], tuple[int, ...]], list]:
    """Group guides with identical boundaries so coincident lines are drawn once."""
    groups = {}
    for guide in details.nine_slice_guides:
        groups.setdefault((guide.x_bounds, guide.y_bounds), []).append(guide)
    return groups


def overlay_presentation_diagnostics(image: Image.Image, details: PreparationDiagnostics) -> Image.Image:
    """Return a copy with literary, effective QR, and resolved nine-slice overlays."""
    literary = annotate_literary_region(image, details.geometry.presentation_literary_bounds)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def outlined(bounds: PixelBounds, color: str, width: int = 4) -> None:
        left, top, right, bottom = bounds
        draw.rectangle((left, top, right - 1, bottom - 1), outline=color, width=width)

    if details.qr_placement is not None:
        outlined(details.qr_placement.presentation_allocation_bounds, "#000000", 8)
        outlined(details.qr_placement.presentation_allocation_bounds, _QR_COLOR, 4)

    groups = guide_groups(details)
    for color_index, (x_bounds, y_bounds) in enumerate(groups):
        color = guide_color(color_index, len(groups))
        for x in x_bounds[1:-1]:
            output_x = round_half_up(x * image.width, details.geometry.design_canvas_size[0])
            if 0 <= output_x < image.width:
                draw.line((output_x, 0, output_x, image.height - 1), fill="#000000", width=4)
                draw.line((output_x, 0, output_x, image.height - 1), fill=color, width=2)
        for y in y_bounds[1:-1]:
            output_y = round_half_up(y * image.height, details.geometry.design_canvas_size[1])
            if 0 <= output_y < image.height:
                draw.line((0, output_y, image.width - 1, output_y), fill="#000000", width=4)
                draw.line((0, output_y, image.width - 1, output_y), fill=color, width=2)

    if groups:
        font = ImageFont.load_default()
        entries = [
            (", ".join(f"Layer {guide.layer_index}" for guide in guides), guide_color(index, len(groups)))
            for index, guides in enumerate(groups.values())
        ]
        line_height = 18
        text_width = max(draw.textbbox((0, 0), label, font=font)[2] for label, _ in entries)
        legend_left = 12
        legend_top = 12
        legend_right = min(image.width - 1, legend_left + text_width + 42)
        legend_bottom = min(image.height - 1, legend_top + len(entries) * line_height + 8)
        draw.rectangle((legend_left, legend_top, legend_right, legend_bottom), fill=(0, 0, 0, 210))
        for index, (label, color) in enumerate(entries):
            top = legend_top + 4 + index * line_height
            draw.line((legend_left + 6, top + 5, legend_left + 22, top + 5), fill="#FFFFFF", width=5)
            draw.line((legend_left + 6, top + 5, legend_left + 22, top + 5), fill=color, width=3)
            draw.text((legend_left + 28, top), label, font=font, fill="#FFFFFF")

    background = literary.convert("RGBA")
    try:
        composed = Image.alpha_composite(background, overlay)
        try:
            return composed.convert(image.mode)
        finally:
            composed.close()
    finally:
        background.close()
        overlay.close()
        literary.close()


__all__ = ["guide_color", "guide_groups", "overlay_presentation_diagnostics"]

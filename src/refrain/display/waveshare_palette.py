"""Hardware-independent palette conversion for the Waveshare 13.3-inch E panel."""

from __future__ import annotations

from PIL import Image

WAVESHARE_ACTIVE_PALETTE = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 255, 0),
    (255, 0, 0),
    (0, 0, 0),
    (0, 0, 255),
    (0, 255, 0),
)
_PALETTE = tuple(channel for color in WAVESHARE_ACTIVE_PALETTE for channel in color) + (0, 0, 0) * (
    256 - len(WAVESHARE_ACTIVE_PALETTE)
)


def quantize_waveshare_palette(image: Image.Image) -> Image.Image:
    """Return a new palette-indexed image using the vendored driver's active palette and dithering."""
    palette = Image.new("P", (1, 1))
    rgb_image = None
    try:
        palette.putpalette(_PALETTE)
        rgb_image = image.convert("RGB")
        return rgb_image.quantize(palette=palette)
    finally:
        palette.close()
        if rgb_image is not None:
            rgb_image.close()

"""Hardware-independent visual post-processing for configured destinations."""

from __future__ import annotations

from PIL import Image

from .waveshare_palette import quantize_waveshare_palette

_WAVESHARE_SIZE = (1600, 1200)
_IDENTITY_DESTINATIONS = {"window", "image-server"}


def post_process_destination_image(destination_type: str, image: Image.Image) -> Image.Image:
    """Return destination-final visual pixels without modifying the completed output image."""
    if not isinstance(image, Image.Image):
        raise TypeError("destination post-processing requires a Pillow Image.Image")
    if destination_type in _IDENTITY_DESTINATIONS:
        return image
    if destination_type == "waveshare-13in3-e":
        if image.mode != "RGB" or image.size != _WAVESHARE_SIZE:
            raise ValueError("Waveshare post-processing requires an RGB image of 1600 x 1200 pixels")
        with quantize_waveshare_palette(image) as indexed_image:
            return indexed_image.convert("RGB")
    raise ValueError(f"unsupported destination type for visual post-processing: {destination_type!r}")

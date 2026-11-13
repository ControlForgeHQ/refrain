from __future__ import annotations

import builtins
import importlib
from unittest.mock import patch

from PIL import Image

from refrain.display import postprocessing
from refrain.display.postprocessing import post_process_destination_image
from refrain.display.waveshare_palette import WAVESHARE_ACTIVE_PALETTE, quantize_waveshare_palette


def test_non_transforming_destinations_preserve_pixels_and_caller_image() -> None:
    image = Image.new("RGB", (3, 2), (25, 50, 75))

    for destination_type in ("window", "image-server"):
        processed = post_process_destination_image(destination_type, image)
        assert processed.size == image.size
        assert processed.mode == image.mode
        assert processed.getpixel((1, 1)) == image.getpixel((1, 1))

    assert image.getpixel((1, 1)) == (25, 50, 75)
    image.close()


def test_waveshare_postprocessing_returns_active_palette_pixels_without_mutation() -> None:
    image = Image.new("RGB", (1600, 1200), (255, 128, 0))

    processed = post_process_destination_image("waveshare-13in3-e", image)

    assert processed.mode == "RGB"
    assert processed.size == image.size
    assert processed.getpixel((0, 0)) == (255, 255, 0)
    assert image.getpixel((0, 0)) == (255, 128, 0)
    with quantize_waveshare_palette(image) as preview_indices:
        with quantize_waveshare_palette(processed) as transport_indices:
            assert transport_indices.tobytes() == preview_indices.tobytes()
    processed.close()
    image.close()


def test_waveshare_palette_order_and_dither_sentinels_match_the_vendored_driver() -> None:
    assert WAVESHARE_ACTIVE_PALETTE == (
        (0, 0, 0),
        (255, 255, 255),
        (255, 255, 0),
        (255, 0, 0),
        (0, 0, 0),
        (0, 0, 255),
        (0, 255, 0),
    )
    colors = [
        (128, 128, 128),
        (220, 220, 220),
        (220, 128, 20),
        (128, 20, 20),
        (20, 128, 20),
        (20, 20, 128),
        (128, 128, 20),
        (255, 128, 0),
    ]
    image = Image.new("RGB", (len(colors), 1))
    image.putdata(colors)

    with quantize_waveshare_palette(image) as result:
        assert result.get_flattened_data() == (1, 1, 3, 0, 6, 5, 2, 3)

    image.close()


def test_waveshare_conversion_is_hardware_independent_and_shared_with_vendor_driver() -> None:
    original_import = builtins.__import__

    def reject_hardware_import(name, *args, **kwargs):
        if name.startswith(("gpiod", "spidev", "refrain.display.vendor.waveshare")):
            raise AssertionError(f"hardware module {name!r} was imported")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=reject_hardware_import):
        importlib.reload(postprocessing)
        image = Image.new("RGB", (1600, 1200), (255, 128, 0))
        processed = post_process_destination_image("waveshare-13in3-e", image)
        assert processed.getpixel((0, 0)) == (255, 255, 0)
        processed.close()
        image.close()

    from refrain.display.vendor.waveshare import epd13in3E

    assert epd13in3E.quantize_waveshare_palette is quantize_waveshare_palette

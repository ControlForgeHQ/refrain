from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import refrain.preparation as preparation
from refrain.config import DecorationLayerResource, DecorationResource, NineSliceParameters


def _nine_slice_layer(
    *,
    horizontal: str = "stretch",
    vertical: str = "stretch",
    image: Path | None = None,
) -> DecorationLayerResource:
    return DecorationLayerResource(
        image or Path("/unused.png"),
        "nine-slice",
        NineSliceParameters(24, 24, 18, 18, horizontal, vertical),
        tintable=False,
    )


def _nine_region_image() -> Image.Image:
    image = Image.new("RGBA", (384, 240))
    draw = ImageDraw.Draw(image)
    colors = (
        ("red", "green", "blue"),
        ("yellow", "magenta", "cyan"),
        ("orange", "white", "black"),
    )
    x_bounds = (0, 24, 360, 384)
    y_bounds = (0, 18, 222, 240)
    for row, y0 in enumerate(y_bounds[:-1]):
        for column, x0 in enumerate(x_bounds[:-1]):
            draw.rectangle(
                (x0, y0, x_bounds[column + 1] - 1, y_bounds[row + 1] - 1),
                fill=colors[row][column],
            )
    return image


def test_source_boundaries_map_to_reference_coordinates_with_shared_rounding() -> None:
    parameters = NineSliceParameters(24, 24, 18, 18)

    assert preparation._mapped_boundaries((384, 240), parameters) == (
        (0, 240, 3600, 3840),
        (0, 180, 2220, 2400),
    )

    odd_parameters = NineSliceParameters(1, 1, 1, 1)
    first = preparation._mapped_boundaries((7, 3), odd_parameters)
    assert first == ((0, 549, 3291, 3840), (377, 926, 1474, 2023))
    assert preparation._mapped_boundaries((7, 3), odd_parameters) == first


@pytest.mark.parametrize("canvas", [(3200, 2400), (3840, 2160), (3840, 2400)])
def test_nine_slice_preserves_240_by_180_corners_across_working_canvases(canvas: tuple[int, int]) -> None:
    source = _nine_region_image()
    background = Image.new("RGB", canvas, (90, 90, 90))
    try:
        preparation._compose_nine_slice(background, source, _nine_slice_layer())

        assert background.getpixel((0, 0)) == (255, 0, 0)
        assert background.getpixel((239, 179)) == (255, 0, 0)
        assert background.getpixel((240, 0)) == (0, 128, 0)
        assert background.getpixel((canvas[0] - 240, 0)) == (0, 0, 255)
        assert background.getpixel((0, 180)) == (255, 255, 0)
        assert background.getpixel((canvas[0] // 2, canvas[1] // 2)) == (255, 0, 255)
        assert background.getpixel((0, canvas[1] - 180)) == (255, 165, 0)
        assert background.getpixel((canvas[0] - 1, canvas[1] - 1)) == (0, 0, 0)
        assert background.getpixel((canvas[0] // 2, canvas[1] - 1)) == (255, 255, 255)
    finally:
        source.close()
        background.close()


def test_nine_slice_crop_trims_each_edge_segment_symmetrically() -> None:
    source = _nine_region_image()
    draw = ImageDraw.Draw(source)
    draw.rectangle((24, 0, 43, 17), fill="blue")
    draw.rectangle((340, 0, 359, 17), fill="orange")
    background = Image.new("RGB", (3200, 2400), (90, 90, 90))
    try:
        preparation._compose_nine_slice(
            background,
            source,
            _nine_slice_layer(horizontal="crop", vertical="crop"),
        )

        assert background.getpixel((240, 10)) == (0, 128, 0)
        assert background.getpixel((2959, 10)) == (0, 128, 0)
        assert background.getpixel((10, 180)) == (255, 255, 0)
        assert background.getpixel((10, 2219)) == (255, 255, 0)
        assert all(background.getpixel((x, 1200)) != (90, 90, 90) for x in range(3200))
    finally:
        source.close()
        background.close()


def test_nine_slice_rejects_corner_and_crop_destinations_that_cannot_fit() -> None:
    source = _nine_region_image()
    background = Image.new("RGB", (3200, 2400), "white")
    too_wide = DecorationLayerResource(
        Path("/unused.png"),
        "nine-slice",
        NineSliceParameters(190, 190, 18, 18),
    )
    try:
        with pytest.raises(ValueError, match="preserved corners"):
            preparation._compose_nine_slice(background, source, too_wide)
    finally:
        source.close()
        background.close()

    source = Image.new("RGBA", (384, 288), "red")
    background = Image.new("RGB", (3840, 2400), "white")
    crop_layer = DecorationLayerResource(
        Path("/unused.png"),
        "nine-slice",
        NineSliceParameters(0, 0, 12, 12, horizontal="crop"),
    )
    try:
        with pytest.raises(ValueError, match="exceeds source edge length"):
            preparation._compose_nine_slice(background, source, crop_layer)
    finally:
        source.close()
        background.close()


def test_invalid_crop_geometry_leaves_destination_unchanged(tmp_path: Path, caplog) -> None:
    image_path = tmp_path / "narrow.png"
    source = Image.new("RGBA", (1000, 2400), (200, 30, 40, 255))
    try:
        source.save(image_path)
    finally:
        source.close()
    layer = DecorationLayerResource(
        image_path,
        "nine-slice",
        NineSliceParameters(20, 20, 20, 20, horizontal="crop"),
        tintable=False,
    )
    decoration = DecorationResource("crop-too-long", (layer,), False)
    background = Image.new("RGB", (3840, 2400), (17, 23, 31))
    original_pixel = background.getpixel((0, 0))

    composed = preparation._apply_daily_decoration(
        background,
        "crop-too-long",
        {"crop-too-long": decoration},
    )

    assert composed is background
    assert background.getpixel((0, 0)) == original_pixel
    assert background.getpixel((24, 24)) == original_pixel
    assert background.getpixel((3839, 2399)) == original_pixel
    assert "horizontal crop destination length" in caplog.text
    background.close()


def _write_layer(path: Path, color: tuple[int, int, int, int], *, size: tuple[int, int] = (4, 2)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)
    return path


def test_conditional_layers_keep_order_and_use_the_resolved_qr_state(tmp_path: Path) -> None:
    paths = [tmp_path / f"layer-{index}.png" for index in range(4)]
    with Image.new("RGBA", (4, 2), (255, 0, 0, 255)) as always:
        always.save(paths[0])
    with Image.new("RGBA", (4, 2), (0, 0, 0, 0)) as qr:
        qr.putpixel((0, 0), (0, 0, 255, 255))
        qr.save(paths[1])
    with Image.new("RGBA", (4, 2), (0, 0, 0, 0)) as no_qr:
        no_qr.putpixel((1, 0), (255, 255, 0, 255))
        no_qr.save(paths[2])
    with Image.new("RGBA", (4, 2), (0, 0, 0, 0)) as final:
        final.putpixel((3, 1), (0, 255, 255, 255))
        final.save(paths[3])
    decoration = DecorationResource(
        "layers",
        (
            DecorationLayerResource(paths[0], "contain", tintable=False),
            DecorationLayerResource(paths[1], "contain", condition="qr", tintable=False),
            DecorationLayerResource(paths[2], "contain", condition="no-qr", tintable=False),
            DecorationLayerResource(paths[3], "contain", tintable=False),
        ),
        False,
    )

    for qr_available, expected_first, expected_second in (
        (True, (0, 0, 255), (255, 0, 0)),
        (False, (255, 0, 0), (255, 255, 0)),
    ):
        background = Image.new("RGB", (4, 2), "white")
        try:
            preparation._apply_daily_decoration(
                background,
                "layers",
                {"layers": decoration},
                qr_available=qr_available,
            )
            assert background.getpixel((0, 0)) == expected_first
            assert background.getpixel((1, 0)) == expected_second
            assert background.getpixel((3, 1)) == (0, 255, 255)
        finally:
            background.close()


def test_tinting_preserves_alpha_and_untinted_layer_rgb(tmp_path: Path) -> None:
    tinted_path = tmp_path / "tinted.png"
    with Image.new("RGBA", (4, 2), (200, 30, 40, 0)) as tinted:
        for x, alpha in enumerate((0, 64, 128, 255)):
            tinted.putpixel((x, 0), (200, 30, 40, alpha))
        tinted.save(tinted_path)
    accent_path = tmp_path / "accent.png"
    with Image.new("RGBA", (4, 2), (0, 0, 0, 0)) as accent:
        accent.putpixel((3, 1), (30, 220, 60, 255))
        accent.save(accent_path)
    decoration = DecorationResource(
        "tinted",
        (
            DecorationLayerResource(tinted_path, "contain"),
            DecorationLayerResource(accent_path, "contain", tintable=False),
        ),
        False,
        tintable=True,
    )
    background = Image.new("RGB", (4, 2), "black")
    try:
        preparation._apply_daily_decoration(background, "tinted", {"tinted": decoration}, (0, 0, 255))

        assert [background.getpixel((x, 0)) for x in range(4)] == [
            (0, 0, 0),
            (0, 0, 64),
            (0, 0, 128),
            (0, 0, 255),
        ]
        assert background.getpixel((3, 1)) == (30, 220, 60)
    finally:
        background.close()


def test_no_effectively_tintable_layer_does_not_resolve_a_colour() -> None:
    class RejectChoice:
        def choice(self, _values):
            raise AssertionError("no decoration color should be selected")

    layer = DecorationLayerResource(Path("/unused.png"), "contain")
    for decoration in (
        DecorationResource("plain", (DecorationLayerResource(Path("/unused.png"), "contain", tintable=False),), False),
        DecorationResource("plain", (layer,), False, tintable=False),
    ):
        assert (
            preparation._resolve_decoration_tint(
                None,
                None,
                decoration,
                RejectChoice(),
                decoration.layers,
            )
            is None
        )

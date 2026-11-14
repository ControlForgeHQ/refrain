from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import refrain.preparation as preparation
from refrain.config import (
    BackgroundLayerResource,
    BackgroundResource,
    DecorationLayerResource,
    DecorationResource,
    LayerAnchor,
    NineSliceParameters,
)


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


def test_source_boundaries_remain_source_pixel_distances_with_shared_boundaries() -> None:
    parameters = NineSliceParameters(24, 24, 18, 18)

    assert preparation._mapped_boundaries((384, 240), parameters) == (
        (0, 24, 360, 384),
        (0, 18, 222, 240),
    )

    odd_parameters = NineSliceParameters(1, 1, 1, 1)
    first = preparation._mapped_boundaries((7, 3), odd_parameters)
    assert first == ((0, 1, 6, 7), (0, 1, 2, 3))
    assert preparation._mapped_boundaries((7, 3), odd_parameters) == first


def test_nine_slice_20_pixel_edges_stay_20_pixels_on_3840_by_2400_design_canvas() -> None:
    source = Image.new("RGBA", (1920, 1200), "green")
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 19, 1199), fill="red")
    draw.rectangle((1900, 0, 1919, 1199), fill="red")
    draw.rectangle((0, 0, 1919, 19), fill="red")
    draw.rectangle((0, 1180, 1919, 1199), fill="red")
    background = Image.new("RGB", (3840, 2400), "white")
    layer = DecorationLayerResource(
        Path("/unused.png"),
        "nine-slice",
        NineSliceParameters(20, 20, 20, 20),
        tintable=False,
    )
    try:
        preparation._compose_nine_slice(background, source, layer)

        assert background.getpixel((19, 1200)) == (255, 0, 0)
        assert background.getpixel((20, 1200)) == (0, 128, 0)
        assert background.getpixel((3819, 1200)) == (0, 128, 0)
        assert background.getpixel((3820, 1200)) == (255, 0, 0)
        assert background.getpixel((1920, 19)) == (255, 0, 0)
        assert background.getpixel((1920, 20)) == (0, 128, 0)
        assert background.getpixel((1920, 2379)) == (0, 128, 0)
        assert background.getpixel((1920, 2380)) == (255, 0, 0)
    finally:
        source.close()
        background.close()


@pytest.mark.parametrize("canvas", [(3200, 2400), (3840, 2160), (3840, 2400)])
def test_nine_slice_preserves_source_pixel_corner_thickness_across_design_canvases(
    canvas: tuple[int, int],
) -> None:
    source = _nine_region_image()
    background = Image.new("RGB", canvas, (90, 90, 90))
    try:
        preparation._compose_nine_slice(background, source, _nine_slice_layer())

        assert background.getpixel((0, 0)) == (255, 0, 0)
        assert background.getpixel((23, 17)) == (255, 0, 0)
        assert background.getpixel((24, 0)) == (0, 128, 0)
        assert background.getpixel((canvas[0] - 24, 0)) == (0, 0, 255)
        assert background.getpixel((0, 18)) == (255, 255, 0)
        assert background.getpixel((canvas[0] // 2, canvas[1] // 2)) == (255, 0, 255)
        assert background.getpixel((0, canvas[1] - 18)) == (255, 165, 0)
        assert background.getpixel((canvas[0] - 1, canvas[1] - 1)) == (0, 0, 0)
        assert background.getpixel((canvas[0] // 2, canvas[1] - 1)) == (255, 255, 255)
    finally:
        source.close()
        background.close()


@pytest.mark.parametrize("canvas", [(3200, 2400), (3840, 2160), (3840, 2400)])
def test_background_nine_slice_matches_decoration_geometry_across_design_canvases(
    tmp_path: Path,
    canvas: tuple[int, int],
) -> None:
    source_path = tmp_path / "nine-slice.png"
    with _nine_region_image() as source:
        source.save(source_path)
    background_resource = BackgroundResource(
        "shared-nine-slice",
        None,
        False,
        (BackgroundLayerResource(source_path, "nine-slice", NineSliceParameters(24, 24, 18, 18)),),
    )
    decoration_resource = DecorationResource(
        "shared-nine-slice",
        (
            DecorationLayerResource(
                source_path,
                "nine-slice",
                NineSliceParameters(24, 24, 18, 18),
                tintable=False,
            ),
        ),
        False,
    )

    background = preparation._generate_daily_background(
        canvas, "shared-nine-slice", {"shared-nine-slice": background_resource}
    )
    decoration_background = Image.new("RGB", canvas, "white")
    try:
        preparation._apply_daily_decoration(
            decoration_background,
            "shared-nine-slice",
            {"shared-nine-slice": decoration_resource},
        )
        assert background.tobytes() == decoration_background.tobytes()
    finally:
        background.close()
        decoration_background.close()


@pytest.mark.parametrize(
    ("scale", "source_size", "canvas", "expected_size"),
    [
        ("horizontal", (4, 2), (8, 6), (8, 4)),
        ("vertical", (4, 2), (8, 6), (12, 6)),
        ("none", (4, 2), (8, 6), (4, 2)),
        ("horizontal", (8, 4), (4, 6), (4, 2)),
        ("vertical", (8, 4), (4, 2), (4, 2)),
    ],
)
def test_anchor_scaling_preserves_aspect_ratio_and_design_canvas_geometry(
    scale: str,
    source_size: tuple[int, int],
    canvas: tuple[int, int],
    expected_size: tuple[int, int],
) -> None:
    source = Image.new("RGBA", source_size, (240, 20, 10, 255))
    background = Image.new("RGB", canvas, "white")
    layer = DecorationLayerResource(
        Path("/unused.png"),
        "anchor",
        scale=scale,
        anchor=LayerAnchor("left", "top"),
        tintable=False,
    )
    try:
        preparation._compose_layer(background, source, layer)

        assert background.getpixel((0, 0)) == (240, 20, 10)
        assert background.getpixel((min(expected_size[0], canvas[0]) - 1, min(expected_size[1], canvas[1]) - 1)) == (
            240,
            20,
            10,
        )
        if expected_size[0] < canvas[0]:
            assert background.getpixel((expected_size[0], 0)) == (255, 255, 255)
        if expected_size[1] < canvas[1]:
            assert background.getpixel((0, expected_size[1])) == (255, 255, 255)
    finally:
        source.close()
        background.close()


@pytest.mark.parametrize("horizontal,expected_x", [("left", 0), ("center", 2), ("right", 4)])
@pytest.mark.parametrize("vertical,expected_y", [("top", 0), ("center", 2), ("bottom", 4)])
def test_anchor_positions_small_artwork_at_each_nine_canvas_position(
    horizontal: str,
    expected_x: int,
    vertical: str,
    expected_y: int,
) -> None:
    source = Image.new("RGBA", (2, 2), (210, 30, 20, 255))
    background = Image.new("RGB", (6, 6), "white")
    layer = DecorationLayerResource(
        Path("/unused.png"),
        "anchor",
        scale="none",
        anchor=LayerAnchor(horizontal, vertical),
        tintable=False,
    )
    try:
        preparation._compose_layer(background, source, layer)

        assert background.getpixel((expected_x, expected_y)) == (210, 30, 20)
        assert background.getpixel((expected_x + 1, expected_y + 1)) == (210, 30, 20)
        assert any(
            background.getpixel((x, y)) == (255, 255, 255)
            for y in range(background.height)
            for x in range(background.width)
            if not (expected_x <= x < expected_x + 2 and expected_y <= y < expected_y + 2)
        )
    finally:
        source.close()
        background.close()


@pytest.mark.parametrize(
    ("horizontal", "vertical", "source_box"),
    [
        ("left", "top", (0, 0, 4, 4)),
        ("center", "center", (1, 1, 5, 5)),
        ("right", "bottom", (2, 2, 6, 6)),
        ("right", "top", (2, 0, 6, 4)),
        ("left", "bottom", (0, 2, 4, 6)),
    ],
)
def test_anchor_clips_oversized_artwork_at_canvas_edges(
    horizontal: str,
    vertical: str,
    source_box: tuple[int, int, int, int],
) -> None:
    source = Image.new("RGBA", (6, 6))
    for y in range(source.height):
        for x in range(source.width):
            source.putpixel((x, y), (x * 30, y * 30, 10, 255))
    background = Image.new("RGB", (4, 4), "white")
    layer = DecorationLayerResource(
        Path("/unused.png"),
        "anchor",
        scale="none",
        anchor=LayerAnchor(horizontal, vertical),
        tintable=False,
    )
    expected = source.crop(source_box)
    try:
        preparation._compose_layer(background, source, layer)

        assert background.tobytes() == expected.convert("RGB").tobytes()
    finally:
        expected.close()
        source.close()
        background.close()


def test_anchor_alpha_composites_after_alignment_and_clipping() -> None:
    source = Image.new("RGBA", (3, 3), (0, 0, 255, 128))
    background = Image.new("RGB", (2, 2), (240, 20, 10))
    layer = DecorationLayerResource(
        Path("/unused.png"),
        "anchor",
        scale="none",
        anchor=LayerAnchor("right", "bottom"),
        tintable=False,
    )
    try:
        preparation._compose_layer(background, source, layer)

        assert background.getpixel((0, 0)) == (120, 10, 133)
        assert background.getpixel((1, 1)) == (120, 10, 133)
    finally:
        source.close()
        background.close()


def test_redundant_anchor_axes_remain_valid_for_fitted_dimensions() -> None:
    source = Image.new("RGBA", (4, 2), (20, 180, 90, 255))
    results = []
    try:
        for horizontal in ("left", "center", "right"):
            background = Image.new("RGB", (8, 6), "white")
            layer = DecorationLayerResource(
                Path("/unused.png"),
                "anchor",
                scale="horizontal",
                anchor=LayerAnchor(horizontal, "top"),
                tintable=False,
            )
            try:
                preparation._compose_layer(background, source, layer)
                results.append(background.tobytes())
            finally:
                background.close()

        assert results[0] == results[1] == results[2]
    finally:
        source.close()


@pytest.mark.parametrize("canvas", [(3200, 2400), (3840, 2160), (3840, 2400)])
def test_anchor_geometry_is_shared_by_background_and_decoration_layers(
    tmp_path: Path,
    canvas: tuple[int, int],
) -> None:
    source_path = tmp_path / "anchor.png"
    with Image.new("RGBA", (40, 24), (10, 140, 220, 180)) as source:
        source.save(source_path)
    anchor = LayerAnchor("right", "top")
    background_resource = BackgroundResource(
        "shared-anchor",
        None,
        False,
        (BackgroundLayerResource(source_path, "anchor", scale="vertical", anchor=anchor),),
    )
    decoration_resource = DecorationResource(
        "shared-anchor",
        (
            DecorationLayerResource(
                source_path,
                "anchor",
                scale="vertical",
                anchor=anchor,
                condition="qr",
                tintable=False,
            ),
        ),
        False,
    )

    background = preparation._generate_daily_background(canvas, "shared-anchor", {"shared-anchor": background_resource})
    decoration_background = Image.new("RGB", canvas, "white")
    try:
        preparation._apply_daily_decoration(
            decoration_background,
            "shared-anchor",
            {"shared-anchor": decoration_resource},
            qr_available=True,
        )
        assert background.tobytes() == decoration_background.tobytes()

        no_qr = Image.new("RGB", canvas, "white")
        try:
            preparation._apply_daily_decoration(
                no_qr,
                "shared-anchor",
                {"shared-anchor": decoration_resource},
                qr_available=False,
            )
            assert no_qr.getpixel((canvas[0] - 1, 0)) == (255, 255, 255)
        finally:
            no_qr.close()
    finally:
        background.close()
        decoration_background.close()


def test_anchor_decoration_condition_and_tinting_preserve_alpha(tmp_path: Path) -> None:
    path = tmp_path / "tinted-anchor.png"
    with Image.new("RGBA", (2, 1), (200, 30, 40, 0)) as source:
        source.putpixel((0, 0), (200, 30, 40, 128))
        source.putpixel((1, 0), (200, 30, 40, 255))
        source.save(path)
    layer = DecorationLayerResource(
        path,
        "anchor",
        scale="none",
        anchor=LayerAnchor("right", "bottom"),
        condition="no-qr",
    )
    decoration = DecorationResource("tinted-anchor", (layer,), False)
    background = Image.new("RGB", (4, 2), "black")
    try:
        preparation._apply_daily_decoration(
            background,
            "tinted-anchor",
            {"tinted-anchor": decoration},
            (0, 0, 255),
            qr_available=False,
        )

        assert background.getpixel((2, 1)) == (0, 0, 128)
        assert background.getpixel((3, 1)) == (0, 0, 255)
        assert background.getpixel((0, 1)) == (0, 0, 0)
    finally:
        background.close()


def test_nine_slice_crop_trims_each_edge_segment_symmetrically() -> None:
    source = Image.new("RGBA", (4000, 2500))
    draw = ImageDraw.Draw(source)
    colors = (
        ("red", "green", "blue"),
        ("yellow", "magenta", "cyan"),
        ("orange", "white", "black"),
    )
    x_bounds = (0, 24, 3976, 4000)
    y_bounds = (0, 18, 2482, 2500)
    for row, y0 in enumerate(y_bounds[:-1]):
        for column, x0 in enumerate(x_bounds[:-1]):
            draw.rectangle(
                (x0, y0, x_bounds[column + 1] - 1, y_bounds[row + 1] - 1),
                fill=colors[row][column],
            )
    draw.rectangle((24, 0, 43, 17), fill="blue")
    draw.rectangle((3956, 0, 3975, 17), fill="orange")
    background = Image.new("RGB", (3200, 2400), (90, 90, 90))
    try:
        preparation._compose_nine_slice(
            background,
            source,
            _nine_slice_layer(horizontal="crop", vertical="crop"),
        )

        assert background.getpixel((24, 10)) == (0, 128, 0)
        assert background.getpixel((3175, 10)) == (0, 128, 0)
        assert background.getpixel((10, 18)) == (255, 255, 0)
        assert background.getpixel((10, 2381)) == (255, 255, 0)
        assert all(background.getpixel((x, 1200)) != (90, 90, 90) for x in range(3200))
    finally:
        source.close()
        background.close()


def test_nine_slice_rejects_corner_and_crop_destinations_that_cannot_fit() -> None:
    source = _nine_region_image()
    background = Image.new("RGB", (300, 2400), "white")
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


@pytest.mark.parametrize(
    "canvas",
    [
        (3200, 2400),
        (3840, 2160),
        (3840, 2400),
    ],
)
def test_cover_crops_reference_artwork_without_scaling(canvas: tuple[int, int]) -> None:
    source = Image.new("RGB", (3840, 2400), (0, 255, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 319, 2399), fill="red")
    draw.rectangle((3520, 0, 3839, 2399), fill="blue")
    draw.rectangle((0, 0, 3839, 119), fill="yellow")
    draw.rectangle((0, 2280, 3839, 2399), fill="magenta")
    draw.rectangle((1900, 1180, 1939, 1219), fill="white")
    background = Image.new("RGB", canvas, "black")
    try:
        preparation._compose_cover(background, source)

        assert background.getpixel((canvas[0] // 2, canvas[1] // 2)) == (255, 255, 255)
        if canvas == (3200, 2400):
            assert background.getpixel((0, 1200)) == (0, 255, 0)
        elif canvas == (3840, 2160):
            assert background.getpixel((1920, 0)) == (0, 255, 0)
        else:
            assert background.getpixel((0, 1200)) == (255, 0, 0)
            assert background.getpixel((3839, 1200)) == (0, 0, 255)
    finally:
        source.close()
        background.close()


def test_cover_enlarges_uniformly_and_crops_odd_excess_deterministically() -> None:
    source = Image.new("RGB", (5, 3))
    for x in range(source.width):
        for y in range(source.height):
            source.putpixel((x, y), (x * 40, y * 80, 0))
    expected = source.resize((7, 4), Image.Resampling.LANCZOS).crop((1, 0, 5, 4))
    background = Image.new("RGB", (4, 4), "black")
    try:
        preparation._compose_cover(background, source)

        assert background.tobytes() == expected.tobytes()
        assert background.getpixel((1, 1)) == expected.getpixel((1, 1))
    finally:
        source.close()
        expected.close()
        background.close()


def test_cover_enlarges_matching_aspect_ratio_without_cropping() -> None:
    source = Image.new("RGB", (4, 3), "black")
    source.putpixel((1, 1), (255, 0, 0))
    expected = source.resize((8, 6), Image.Resampling.LANCZOS)
    background = Image.new("RGB", (8, 6), "white")
    try:
        preparation._compose_cover(background, source)

        assert background.tobytes() == expected.tobytes()
    finally:
        source.close()
        expected.close()
        background.close()


def test_cover_matching_source_avoids_resampling(monkeypatch) -> None:
    source = Image.new("RGB", (4, 2), "red")
    background = Image.new("RGB", source.size, "black")

    def reject_resampling(*_args, **_kwargs):
        raise AssertionError("matching cover source must not be transformed")

    monkeypatch.setattr(source, "resize", reject_resampling)
    monkeypatch.setattr(source, "crop", reject_resampling)
    try:
        preparation._compose_cover(background, source)

        assert background.getpixel((0, 0)) == (255, 0, 0)
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
    with Image.new("RGBA", (2, 1), (255, 0, 0, 255)) as always:
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
            DecorationLayerResource(paths[0], "cover", tintable=False),
            DecorationLayerResource(paths[1], "cover", condition="qr", tintable=False),
            DecorationLayerResource(paths[2], "cover", condition="no-qr", tintable=False),
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
            DecorationLayerResource(tinted_path, "cover"),
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

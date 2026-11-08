from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from importlib.resources import files
from pathlib import Path

import pytest
from PIL import Image

import refrain.preparation as preparation
from refrain import (
    ApplicationConfiguration,
    CompositionVisibility,
    DailyImagePreparationError,
    DailySnapshot,
    DisplayBackendConfiguration,
    FontResource,
    PresentationRegion,
    RevealSchedule,
    SchedulingContext,
    resolve_reveal_stages,
)
from refrain import (
    prepare_daily_images as _prepare_daily_images,
)
from refrain.config import BackgroundResource, DecorationResource

_IMAGE_SIZE = (1600, 1200)
_LORA = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
_LORA_ITALIC = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Italic.ttf")
_FONT_REGISTRY = {"lora": FontResource("lora", _LORA, bundled=True)}
_MULTI_FACE_REGISTRY = {
    "lora": FontResource(
        "lora",
        _LORA,
        bundled=True,
        faces={"regular": _LORA, "italic": _LORA_ITALIC},
    )
}


@pytest.fixture
def embedded_font() -> str:
    return "lora"


def make_snapshot(
    font_identifier: str,
    *,
    source: str | None = "A Sample Collection",
    attribution: str | None = "An Example Author",
    style: str = "centered",
    metadata: dict[str, object] | None = None,
) -> DailySnapshot:
    if metadata is None:
        metadata = {"presentation_style": style, "source": source, "attribution": attribution}
    text_color = metadata.get("text_color")
    if text_color is None and isinstance(metadata.get("text_color_identifier"), str):
        text_color = (metadata["text_color_identifier"],)
    decoration_color = metadata.get("decoration_color")
    if decoration_color is None and isinstance(metadata.get("decoration_color_identifier"), str):
        decoration_color = (metadata["decoration_color_identifier"],)
    return DailySnapshot(
        entry_id="test-entry",
        quotation_text="A small thought, carefully kept.",
        quotation_identity="A small thought, carefully kept.",
        source=metadata.get("source", source),
        attribution=metadata.get("attribution", attribution),
        presentation_style=metadata.get("presentation_style", style),
        font=font_identifier,
        font_faces=metadata.get("font_faces", {}),
        background=None,
        decoration=None,
        text_color=text_color,
        decoration_color=decoration_color,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 10, 26), "06:00"),
    )


def _configuration(
    fonts: dict[str, FontResource],
    backgrounds: dict[str, BackgroundResource] | None = None,
    decorations: dict[str, DecorationResource] | None = None,
    *,
    region: PresentationRegion = PresentationRegion(0.1, 0.1, 0.8, 0.8),
    min_font_size: int = 12,
    max_font_size: int = 32,
    default_fonts: tuple[str, ...] | None = None,
    default_backgrounds: tuple[str, ...] = ("none",),
    default_decorations: tuple[str, ...] = ("none",),
) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        file=Path("/config.yaml"),
        display_backends=(DisplayBackendConfiguration("window"),),
        day_start=time(6),
        content_directory=Path("/content"),
        reveal=RevealSchedule(time(12), time(18)),
        presentation_region=region,
        fonts=fonts,
        default_fonts=tuple(fonts) if default_fonts is None else default_fonts,
        min_font_size=min_font_size,
        max_font_size=max_font_size,
        backgrounds={} if backgrounds is None else backgrounds,
        default_backgrounds=default_backgrounds,
        decorations={} if decorations is None else decorations,
        default_decorations=default_decorations,
        palette={"black": "#000000", "burnt-orange": "#C65A20", "blue": "#0000FF"},
        default_text_colors=("black",),
        default_decoration_colors=("black",),
    )


def prepare_daily_images(
    snapshot: DailySnapshot,
    stages,
    fonts,
    backgrounds=None,
    decorations=None,
    **kwargs,
):
    backgrounds = kwargs.pop("background_registry", backgrounds)
    decorations = kwargs.pop("decoration_registry", decorations)
    configuration = (
        fonts
        if isinstance(fonts, ApplicationConfiguration)
        else _configuration(
            fonts,
            backgrounds,
            decorations,
            region=kwargs.pop("region", PresentationRegion(0.1, 0.1, 0.8, 0.8)),
            min_font_size=kwargs.pop("min_font_size", 12),
            max_font_size=kwargs.pop("max_font_size", 32),
            default_fonts=kwargs.pop("default_fonts", None),
            default_backgrounds=kwargs.pop("default_backgrounds", ("none",)),
            default_decorations=kwargs.pop("default_decorations", ("none",)),
        )
    )
    return _prepare_daily_images(snapshot, stages, configuration, **kwargs)


@pytest.mark.parametrize(
    ("source", "attribution", "stages"),
    [
        (None, None, (CompositionVisibility(),)),
        ("A Sample Collection", None, (CompositionVisibility(), CompositionVisibility(source=True))),
        (None, "An Example Author", (CompositionVisibility(), CompositionVisibility(attribution=True))),
        (
            "A Sample Collection",
            "An Example Author",
            (
                CompositionVisibility(),
                CompositionVisibility(source=True),
                CompositionVisibility(source=True, attribution=True),
            ),
        ),
    ],
)
def test_prepares_all_optional_field_combinations_from_one_embedded_layout(
    embedded_font: str,
    monkeypatch: pytest.MonkeyPatch,
    source: str | None,
    attribution: str | None,
    stages: tuple[CompositionVisibility, ...],
) -> None:
    snapshot = make_snapshot(embedded_font, source=source, attribution=attribution)
    original_snapshot = snapshot
    original_layout = preparation.layout_composition
    resolved_layouts = []

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        resolved_layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)

    images = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)

    assert len(resolved_layouts) == 1
    layout = resolved_layouts[0]
    assert layout.font_identifier == embedded_font
    assert (layout.quotation.text, layout.byline is not None) == (
        snapshot.quotation_text,
        source is not None or attribution is not None,
    )
    assert len(images) == len(stages)
    assert all(image.mode == "RGB" and image.size == _IMAGE_SIZE for image in images)
    assert all(image.getpixel((0, 0)) == (255, 255, 255) for image in images)
    assert len({id(image) for image in images}) == len(images)
    if len(images) > 1:
        assert images[0].tobytes() != images[-1].tobytes()
    assert snapshot == original_snapshot


def test_canonical_reveal_stages_can_be_passed_directly_to_preparation(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font, source="A Sample Collection", attribution="An Example Author")
    stages = resolve_reveal_stages(snapshot)

    images = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)

    assert stages == (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )
    assert len(images) == len(stages)
    for image in images:
        image.close()


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_background_is_beneath_quotation_and_alpha_exposes_white(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "paper.png"
    color = (80, 120, 160) if mode == "RGB" else (80, 120, 160, 255)
    with Image.new(mode, (1600, 1200), color) as background:
        if mode == "RGBA":
            background.putpixel((0, 0), (0, 0, 0, 0))
            background.putpixel((1, 0), (0, 0, 0, 128))
        background.save(path)
    snapshot = replace(
        make_snapshot("lora", source=None, attribution=None),
        background="paper",
    )
    images = prepare_daily_images(
        snapshot, (CompositionVisibility(),), _FONT_REGISTRY, {"paper": BackgroundResource("paper", path, False)}
    )
    try:
        image = images[0]
        assert image.getpixel((10, 10)) == color[:3]
        assert (0, 0, 0) in image.get_flattened_data()
        if mode == "RGBA":
            assert image.getpixel((0, 0)) == (255, 255, 255)
            assert image.getpixel((1, 0)) == (127, 127, 127)
    finally:
        for image in images:
            image.close()


def test_qr_is_composited_last_over_background_and_decoration_for_every_stage(tmp_path: Path) -> None:
    background_path = tmp_path / "paper.png"
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGB", (1600, 1200), (80, 120, 160)) as background:
        background.save(background_path)
    with Image.new("RGBA", (1600, 1200), (200, 20, 40, 255)) as decoration:
        decoration.save(decoration_path)
    snapshot = replace(
        make_snapshot(
            "lora",
            source="A Sample Collection",
        ),
        background="paper",
        decoration="overlay",
    )
    stages = resolve_reveal_stages(snapshot)
    images = prepare_daily_images(
        snapshot,
        stages,
        _FONT_REGISTRY,
        {"paper": BackgroundResource("paper", background_path, False)},
        {"overlay": DecorationResource("overlay", decoration_path, False)},
        region=PresentationRegion(0.75, 0.75, 0.2, 0.2),
        min_font_size=16,
        max_font_size=24,
    )
    try:
        assert all(image.mode == "RGB" and image.size == (1600, 1200) for image in images)
        assert images[0].getpixel((10, 10)) == (200, 20, 40)
        for image in images[1:]:
            assert image.crop((1437, 1037, 1560, 1160)).tobytes() == images[0].crop((1437, 1037, 1560, 1160)).tobytes()
        assert images[0].getpixel((1437, 1037)) == (255, 255, 255)
        assert images[0].getpixel((1449, 1049)) == (0, 0, 0)
        assert snapshot.decoration == "overlay"
    finally:
        for image in images:
            image.close()


def test_decoration_overlays_background_with_rgba_transparency_before_text(tmp_path: Path) -> None:
    background_path = tmp_path / "paper.png"
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGB", (1600, 1200), (80, 120, 160)) as background:
        background.save(background_path)
    with Image.new("RGBA", (1600, 1200), (200, 20, 40, 128)) as decoration:
        decoration.putpixel((0, 0), (200, 20, 40, 0))
        decoration.save(decoration_path)
    snapshot = replace(
        make_snapshot(
            "lora",
            source=None,
            attribution=None,
        ),
        background="paper",
        decoration="overlay",
    )

    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        _FONT_REGISTRY,
        {"paper": BackgroundResource("paper", background_path, False)},
        {"overlay": DecorationResource("overlay", decoration_path, False)},
    )
    try:
        image = images[0]
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (80, 120, 160)
        assert image.getpixel((10, 10)) == (140, 70, 100)
    finally:
        for image in images:
            image.close()


def test_decoration_color_preference_resolves_during_preparation_and_preserves_alpha(tmp_path: Path) -> None:
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGBA", _IMAGE_SIZE, (20, 40, 60, 255)) as decoration:
        decoration.putpixel((0, 0), (0, 0, 0, 0))
        decoration.putpixel((1, 0), (255, 255, 255, 128))
        decoration.putpixel((2, 0), (0, 0, 0, 255))
        decoration.putpixel((3, 0), (40, 80, 120, 128))
        decoration.save(decoration_path)
    original_bytes = decoration_path.read_bytes()
    snapshot = replace(
        make_snapshot(
            "lora",
            source=None,
            attribution=None,
            metadata={
                "presentation_style": "centered",
                "decoration_color_identifier": "burnt-orange",
            },
        ),
        decoration="overlay",
    )

    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(), CompositionVisibility()),
        _FONT_REGISTRY,
        decoration_registry={"overlay": DecorationResource("overlay", decoration_path, False, tintable=True)},
    )
    try:
        for image in images:
            assert image.getpixel((0, 0)) == (255, 255, 255)
            assert image.getpixel((2, 0)) == (198, 90, 32)
            assert image.getpixel((1, 0)) != (255, 255, 255)
            assert image.getpixel((3, 0)) != (40, 80, 120)
        assert images[0].tobytes() == images[1].tobytes()
        assert decoration_path.read_bytes() == original_bytes
    finally:
        for image in images:
            image.close()


def test_unrequested_decoration_color_uses_current_default_palette(tmp_path: Path) -> None:
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGBA", _IMAGE_SIZE, (255, 255, 255, 255)) as decoration:
        decoration.putpixel((0, 0), (40, 80, 120, 255))
        decoration.save(decoration_path)
    snapshot = replace(make_snapshot("lora", source=None, attribution=None), decoration="overlay")

    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        _FONT_REGISTRY,
        decoration_registry={"overlay": DecorationResource("overlay", decoration_path, False, tintable=True)},
    )
    try:
        assert images[0].getpixel((0, 0)) == (0, 0, 0)
        assert images[0].getpixel((10, 10)) == (0, 0, 0)
    finally:
        for image in images:
            image.close()


def test_background_cover_scaling_crops_center(tmp_path: Path) -> None:
    path = tmp_path / "wide.png"
    with Image.new("RGB", (8, 2), (240, 20, 10)) as source:
        for x in range(3, 5):
            for y in range(source.height):
                source.putpixel((x, y), (10, 20, 240))
        source.save(path)

    background = preparation._generate_daily_background(
        (4, 4), "wide", {"wide": BackgroundResource("wide", path, False)}
    )
    try:
        assert background.size == (4, 4)
        assert background.mode == "RGB"
        assert background.getpixel((1, 1))[2] > background.getpixel((1, 1))[0]
        assert background.getpixel((2, 2))[2] > background.getpixel((2, 2))[0]
    finally:
        background.close()


def test_background_cover_scaling_preserves_alpha(tmp_path: Path) -> None:
    path = tmp_path / "transparent.png"
    Image.new("RGBA", (4, 2), (10, 20, 240, 128)).save(path)

    background = preparation._generate_daily_background(
        (8, 4), "transparent", {"transparent": BackgroundResource("transparent", path, False)}
    )
    try:
        assert background.size == (8, 4)
        assert background.getpixel((4, 2)) == (132, 137, 247)
    finally:
        background.close()


def test_decoration_contain_scaling_centres_transparent_portrait(tmp_path: Path) -> None:
    path = tmp_path / "portrait.png"
    with Image.new("RGBA", (2, 4), (220, 40, 20, 128)) as source:
        source.save(path)
    background = Image.new("RGB", (8, 4), (80, 120, 160))

    composed = preparation._apply_daily_decoration(
        background,
        "portrait",
        {"portrait": DecorationResource("portrait", path, False)},
    )
    try:
        assert composed.size == (8, 4)
        assert composed.getpixel((0, 0)) == (80, 120, 160)
        assert composed.getpixel((2, 1)) == (80, 120, 160)
        assert composed.getpixel((3, 1)) == (150, 80, 90)
        assert composed.getpixel((4, 1)) == (150, 80, 90)
        assert composed.getpixel((5, 1)) == (80, 120, 160)
    finally:
        composed.close()


def test_missing_committed_decoration_is_omitted_without_changing_snapshot(tmp_path: Path, caplog) -> None:
    snapshot = replace(make_snapshot("lora"), decoration="removed-decoration")

    images = prepare_daily_images(snapshot, (CompositionVisibility(),), _FONT_REGISTRY, {}, {})
    try:
        assert images[0].getpixel((0, 0)) == (255, 255, 255)
        assert snapshot.decoration == "removed-decoration"
        assert "Requested decoration 'removed-decoration' is unavailable" in caplog.text
    finally:
        for image in images:
            image.close()


def test_unavailable_visual_preferences_fall_back_without_changing_snapshot(caplog) -> None:
    snapshot = replace(make_snapshot("lora"), decoration="missing-frame", background="missing-paper")
    images = prepare_daily_images(snapshot, resolve_reveal_stages(snapshot), _FONT_REGISTRY, {}, {})
    try:
        assert images[0].getpixel((0, 0)) == (255, 255, 255)
        assert snapshot.decoration == "missing-frame"
        assert snapshot.background == "missing-paper"
        assert "Requested decoration 'missing-frame' is unavailable" in caplog.text
        assert "Requested background 'missing-paper' from content entry is unavailable" in caplog.text
    finally:
        for image in images:
            image.close()


@pytest.mark.parametrize("kwargs", [{}, {"background_registry": None}, {"background_registry": {}}])
def test_none_background_allows_omitted_or_empty_registry(kwargs) -> None:
    snapshot = make_snapshot("lora")
    images = prepare_daily_images(snapshot, resolve_reveal_stages(snapshot), _FONT_REGISTRY, **kwargs)
    try:
        assert all(image.getpixel((0, 0)) == (255, 255, 255) for image in images)
    finally:
        for image in images:
            image.close()


@pytest.mark.parametrize("damage", ["missing-id", "missing-file", "invalid-file"])
def test_unusable_committed_background_warns_and_uses_white(tmp_path: Path, caplog, damage: str) -> None:
    path = tmp_path / "missing.png"
    registry = {} if damage == "missing-id" else {"paper": BackgroundResource("paper", path, False)}
    if damage == "invalid-file":
        path.write_text("not a PNG")
    snapshot = replace(make_snapshot("lora"), background="paper")
    images = prepare_daily_images(snapshot, resolve_reveal_stages(snapshot), _FONT_REGISTRY, registry)
    try:
        assert all(image.getpixel((0, 0)) == (255, 255, 255) for image in images)
        assert snapshot.background == "paper"
        if damage == "missing-id":
            assert "Requested background 'paper' from content entry is unavailable" in caplog.text
        else:
            assert "Committed background 'paper'" in caplog.text
            assert "paper-white base" in caplog.text
    finally:
        for image in images:
            image.close()


@pytest.mark.parametrize("error", [SyntaxError("malformed PNG chunk"), Image.DecompressionBombError("oversized image")])
def test_background_decode_errors_fall_back_to_white(tmp_path: Path, monkeypatch, caplog, error) -> None:
    def unreadable(resource):
        raise error

    monkeypatch.setattr(preparation, "load_background_image", unreadable)
    snapshot = replace(make_snapshot("lora"), background="paper")
    images = prepare_daily_images(
        snapshot,
        resolve_reveal_stages(snapshot),
        _FONT_REGISTRY,
        {"paper": BackgroundResource("paper", tmp_path / "paper.png", False)},
    )
    try:
        assert all(image.getpixel((0, 0)) == (255, 255, 255) for image in images)
        assert "paper-white base" in caplog.text
    finally:
        for image in images:
            image.close()


def test_preparation_is_deterministic(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font)
    stages = (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )

    first = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)
    second = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)

    assert tuple(image.tobytes() for image in first) == tuple(image.tobytes() for image in second)


def test_committed_color_is_rendered_for_all_literary_fields_and_reveal_stages() -> None:
    snapshot = make_snapshot(
        "lora",
        metadata={
            "presentation_style": "centered",
            "source": "A Sample Collection",
            "attribution": "An Example Author",
            "text_color_identifier": "burnt-orange",
        },
    )
    stages = resolve_reveal_stages(snapshot)
    resolved_layouts = []
    original_layout = preparation.layout_composition

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        resolved_layouts.append(layout)
        return layout

    preparation.layout_composition = capture_layout
    try:
        images = prepare_daily_images(snapshot, stages, _FONT_REGISTRY)
    finally:
        preparation.layout_composition = original_layout

    layout = resolved_layouts[0]
    assert layout.byline is not None
    visible_fields = [
        layout.quotation,
        layout.byline.prefix,
        layout.byline.separator,
        layout.byline.source,
        layout.byline.attribution,
    ]
    assert all(field is not None for field in visible_fields)

    def has_selected_color(bounds: tuple[int, int, int, int], image: Image.Image) -> bool:
        return any(red > green > blue for red, green, blue in image.crop(bounds).get_flattened_data())

    for image, stage in zip(images, stages, strict=True):
        assert has_selected_color(layout.quotation.bounds, image)
        assert has_selected_color(layout.byline.prefix.bounds, image)
        if stage.source:
            assert has_selected_color(layout.byline.source.bounds, image)
        if stage.attribution:
            assert has_selected_color(layout.byline.attribution.bounds, image)

    legacy_snapshot = make_snapshot("lora")
    legacy_layouts = []

    def capture_legacy_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        legacy_layouts.append(layout)
        return layout

    preparation.layout_composition = capture_legacy_layout
    try:
        legacy_images = prepare_daily_images(
            legacy_snapshot,
            resolve_reveal_stages(legacy_snapshot),
            _FONT_REGISTRY,
        )
    finally:
        preparation.layout_composition = original_layout
    legacy_layout_result = legacy_layouts[0]
    assert legacy_layout_result.byline is not None
    assert any(
        red == green == blue and red < 255
        for red, green, blue in legacy_images[-1]
        .crop(legacy_layout_result.byline.attribution.bounds)
        .get_flattened_data()
    )


def test_uses_committed_presentation_style(embedded_font: str, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = make_snapshot(embedded_font, style="left-aligned")
    original_layout = preparation.layout_composition
    resolved_layouts = []

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        resolved_layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)

    prepare_daily_images(snapshot, (CompositionVisibility(),), _FONT_REGISTRY)

    assert resolved_layouts[0].style == "left-aligned"


def test_preparation_uses_committed_faces_for_each_role_and_all_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = make_snapshot(
        "lora",
        metadata={
            "presentation_style": "centered",
            "source": "A Sample Collection",
            "attribution": "An Example Author",
            "font_faces": {"quotation": "regular", "source": "italic", "attribution": "italic"},
        },
    )
    original_layout = preparation.layout_composition
    layouts = []

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)
    stages = resolve_reveal_stages(snapshot)

    images = prepare_daily_images(snapshot, stages, _MULTI_FACE_REGISTRY)

    assert len(layouts) == 1
    layout = layouts[0]
    assert layout.font_identifier == "lora"
    assert layout.source_font_identifier == "lora:italic"
    assert layout.attribution_font_identifier == "lora:italic"
    assert layout.byline is not None
    assert all(image.size == _IMAGE_SIZE for image in images)
    assert dict(snapshot.font_faces) == {
        "quotation": "regular",
        "source": "italic",
        "attribution": "italic",
    }


def test_missing_committed_face_uses_regular_without_changing_snapshot(caplog) -> None:
    snapshot = make_snapshot(
        "lora",
        metadata={
            "presentation_style": "centered",
            "source": "A Sample Collection",
            "attribution": "An Example Author",
            "font_faces": {"quotation": "regular", "source": "missing", "attribution": "italic"},
        },
    )

    images = prepare_daily_images(snapshot, resolve_reveal_stages(snapshot), _MULTI_FACE_REGISTRY)

    assert images
    assert "Preferred source face 'missing'" in caplog.text
    assert dict(snapshot.font_faces)["source"] == "missing"


def test_missing_bundle_fallback_uses_committed_face_identifiers(caplog) -> None:
    snapshot = make_snapshot(
        "removed-bundle",
        metadata={
            "presentation_style": "centered",
            "source": "A Sample Collection",
            "attribution": "An Example Author",
            "font_faces": {"quotation": "regular", "source": "italic", "attribution": "regular"},
        },
    )
    original_layout = preparation.layout_composition
    layouts = []

    def capture_layout(*args: object, **kwargs: object):
        layout = original_layout(*args, **kwargs)
        layouts.append(layout)
        return layout

    preparation.layout_composition = capture_layout
    try:
        images = prepare_daily_images(snapshot, resolve_reveal_stages(snapshot), _MULTI_FACE_REGISTRY)
    finally:
        preparation.layout_composition = original_layout

    assert images
    assert layouts[0].source_font_identifier == "lora:italic"
    assert snapshot.font == "removed-bundle"
    assert "Requested font 'removed-bundle' from content entry is unavailable" in caplog.text


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"presentation_style": "unknown"}, "presentation_style"),
        ({"presentation_style": "centered", "source": ""}, "source"),
    ],
)
def test_invalid_semantic_preferences_are_rejected(
    metadata: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_snapshot("lora", metadata=metadata)


def test_invalid_stage_sequence_is_rejected(embedded_font: str) -> None:
    with pytest.raises(DailyImagePreparationError, match="nonempty sequence"):
        prepare_daily_images(make_snapshot(embedded_font), (), _FONT_REGISTRY)


def test_non_cumulative_or_absent_field_reveal_fails_without_mutation(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font, source=None, attribution=None)
    original_snapshot = snapshot

    with pytest.raises(DailyImagePreparationError, match="cannot reveal a field that is absent"):
        prepare_daily_images(
            snapshot,
            (CompositionVisibility(), CompositionVisibility(source=True)),
            _FONT_REGISTRY,
        )

    assert snapshot == original_snapshot


def test_reveal_stages_must_remain_cumulative(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font)

    with pytest.raises(DailyImagePreparationError, match="reveal stages must be cumulative"):
        prepare_daily_images(
            snapshot,
            (
                CompositionVisibility(),
                CompositionVisibility(source=True),
                CompositionVisibility(),
            ),
            _FONT_REGISTRY,
        )


def test_missing_font_fails_when_default_pool_is_empty() -> None:
    snapshot = make_snapshot("missing-font")

    with pytest.raises(DailyImagePreparationError, match="configure a usable identifier in layout.fonts.default"):
        prepare_daily_images(snapshot, (CompositionVisibility(),), {}, default_fonts=())


def test_unusable_explicit_font_uses_configured_default_pool(tmp_path, caplog, monkeypatch) -> None:
    broken_path = tmp_path / "broken.ttf"
    broken_path.write_bytes(b"not a font")
    snapshot = make_snapshot("broken")
    registry = {
        "broken": FontResource("broken", broken_path, bundled=False),
        "a-fallback": FontResource("a-fallback", _LORA, bundled=True),
        "z-fallback": FontResource("z-fallback", _LORA, bundled=True),
    }
    original_layout = preparation.layout_composition
    layouts = []

    def capture_layout(*args, **kwargs):
        layout = original_layout(*args, **kwargs)
        layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)

    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        registry,
        default_fonts=("a-fallback",),
    )

    assert images[0].size == _IMAGE_SIZE
    assert layouts[0].font_identifier == "a-fallback"
    assert "broken" in caplog.text


def test_composition_that_cannot_fit_fails_without_mutation(embedded_font: str) -> None:
    snapshot = make_snapshot(embedded_font, source=None, attribution=None)
    original_snapshot = snapshot

    with pytest.raises(DailyImagePreparationError, match="does not fit"):
        prepare_daily_images(
            snapshot,
            (CompositionVisibility(),),
            _FONT_REGISTRY,
            region=PresentationRegion(0.49, 0.49, 0.02, 0.02),
            min_font_size=24,
            max_font_size=28,
        )

    assert snapshot == original_snapshot


def test_non_snapshot_input_fails_clearly() -> None:
    with pytest.raises(DailyImagePreparationError, match="DailySnapshot"):
        prepare_daily_images(None, (CompositionVisibility(),), _FONT_REGISTRY)  # type: ignore[arg-type]

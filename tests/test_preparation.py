from __future__ import annotations

from dataclasses import replace
from datetime import date, time
from importlib.resources import files
from pathlib import Path
from random import Random

import pytest
from PIL import Image

import refrain.preparation as preparation
from refrain import (
    ApplicationConfiguration,
    CompositionVisibility,
    DailyImagePreparationError,
    DailySnapshot,
    DisplayBackendConfiguration,
    DisplayOutputConfiguration,
    FontResource,
    PresentationInsets,
    PresentationOverrides,
    ResolvedOutputSpecification,
    RevealSchedule,
    SchedulingContext,
    resolve_reveal_stages,
)
from refrain import (
    prepare_daily_images as _prepare_daily_image_variants,
)
from refrain.config import BackgroundLayerResource, BackgroundResource, DecorationLayerResource, DecorationResource

_DEFAULT_SPECIFICATION = ResolvedOutputSpecification("16:9", (1920, 1080))
_IMAGE_SIZE = _DEFAULT_SPECIFICATION.requested_output_size
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
    insets: PresentationInsets = PresentationInsets(384, 384, 216, 216),
    output_specification: ResolvedOutputSpecification = _DEFAULT_SPECIFICATION,
    min_font_size: int = 12,
    max_font_size: int = 32,
    default_fonts: tuple[str, ...] | None = None,
    default_backgrounds: tuple[str, ...] = ("none",),
    default_decorations: tuple[str, ...] = ("none",),
    qr_enabled: bool = True,
) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        file=Path("/config.yaml"),
        display_backends=(
            DisplayBackendConfiguration(
                "window",
                outputs=(DisplayOutputConfiguration("window", output_specification),),
            ),
        ),
        day_start=time(6),
        content_directory=Path("/content"),
        reveal=RevealSchedule(time(12), time(18)),
        presentation_insets=insets,
        fonts=fonts,
        default_fonts=tuple(fonts) if default_fonts is None else default_fonts,
        min_font_size=min_font_size,
        max_font_size=max_font_size,
        qr_enabled=qr_enabled,
        backgrounds={} if backgrounds is None else backgrounds,
        default_backgrounds=default_backgrounds,
        decorations={} if decorations is None else decorations,
        default_decorations=default_decorations,
        palette={"black": "#000000", "burnt-orange": "#C65A20", "blue": "#0000FF"},
        default_text_colors=("black",),
        default_decoration_colors=("black",),
    )


def _decoration_resource(identifier: str, image_path: Path, bundled: bool = False, **kwargs) -> DecorationResource:
    kwargs.setdefault("tintable", False)
    return DecorationResource(
        identifier,
        (DecorationLayerResource(image_path, "contain"),),
        bundled,
        **kwargs,
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
            insets=kwargs.pop("insets", PresentationInsets(384, 384, 216, 216)),
            output_specification=kwargs.pop("output_specification", _DEFAULT_SPECIFICATION),
            min_font_size=kwargs.pop("min_font_size", 12),
            max_font_size=kwargs.pop("max_font_size", 32),
            default_fonts=kwargs.pop("default_fonts", None),
            default_backgrounds=kwargs.pop("default_backgrounds", ("none",)),
            default_decorations=kwargs.pop("default_decorations", ("none",)),
        )
    )
    variants = _prepare_daily_image_variants(
        snapshot,
        stages,
        configuration,
        configuration.required_output_specifications,
        **kwargs,
    )
    return variants[configuration.required_output_specifications[0]]


def _prepare_configured_images(snapshot, stages, configuration, **kwargs):
    variants = _prepare_daily_image_variants(
        snapshot,
        stages,
        configuration,
        configuration.required_output_specifications,
        **kwargs,
    )
    return variants[configuration.required_output_specifications[0]]


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


@pytest.mark.parametrize(
    "specification",
    [
        ResolvedOutputSpecification("4:3", (1600, 1200)),
        ResolvedOutputSpecification("16:9", (1920, 1080)),
        ResolvedOutputSpecification("16:10", (3840, 2400)),
        ResolvedOutputSpecification("16:10", (808, 505)),
    ],
)
def test_prepared_reveal_images_use_destination_output_resolution(
    specification: ResolvedOutputSpecification,
) -> None:
    snapshot = make_snapshot("lora")
    configuration = _configuration(_FONT_REGISTRY, output_specification=specification)

    images = _prepare_configured_images(
        snapshot,
        resolve_reveal_stages(snapshot),
        configuration,
    )
    try:
        assert len(images) == 3
        assert all(image.size == specification.requested_output_size for image in images)
        assert all(image.mode == "RGB" for image in images)
    finally:
        for image in images:
            image.close()


def test_presentation_choices_are_shared_across_output_specifications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    background_a = tmp_path / "background-a.png"
    background_b = tmp_path / "background-b.png"
    layer_qr = tmp_path / "layer-qr.png"
    layer_no_qr = tmp_path / "layer-no-qr.png"
    for path, color in (
        (background_a, (220, 220, 220)),
        (background_b, (230, 230, 230)),
        (layer_qr, (0, 0, 0)),
        (layer_no_qr, (0, 0, 0)),
    ):
        with Image.new("RGB", (8, 8), color) as image:
            image.save(path)

    def decoration(identifier: str) -> DecorationResource:
        return DecorationResource(
            identifier,
            (
                DecorationLayerResource(layer_qr, "contain", condition="qr"),
                DecorationLayerResource(layer_no_qr, "contain", condition="no-qr"),
            ),
            False,
        )

    fonts = {
        "lora": _FONT_REGISTRY["lora"],
        "lora-alt": FontResource("lora-alt", _LORA, bundled=True),
    }
    backgrounds = {
        "paper-a": BackgroundResource("paper-a", background_a, False),
        "paper-b": BackgroundResource("paper-b", background_b, False),
    }
    decorations = {"frame-a": decoration("frame-a"), "frame-b": decoration("frame-b")}
    configuration = _configuration(
        fonts,
        backgrounds,
        decorations,
        default_fonts=("lora", "lora-alt"),
        default_backgrounds=("paper-a", "paper-b"),
        default_decorations=("frame-a", "frame-b"),
    )
    configuration = replace(
        configuration,
        default_text_colors=("black", "burnt-orange"),
        default_decoration_colors=("black", "blue"),
    )

    class AlternatingChooser:
        def __init__(self) -> None:
            self.counts: dict[tuple[str, ...], int] = {}

        def choice(self, values):
            pool = tuple(values)
            index = self.counts.get(pool, 0)
            self.counts[pool] = index + 1
            return pool[index % len(pool)]

    chooser = AlternatingChooser()
    specifications = (
        ResolvedOutputSpecification("4:3", (80, 60)),
        ResolvedOutputSpecification("16:10", (3840, 2400)),
    )
    snapshot = replace(
        make_snapshot("missing-font", source=None, attribution=None),
        quotation_text="A",
        quotation_identity="A",
    )
    resolved_fonts: list[str] = []
    resolved_backgrounds: list[str] = []
    resolved_decorations: list[str] = []
    resolved_tints: list[tuple[int, int, int] | None] = []
    resolved_text_colors: list[tuple[int, int, int]] = []
    diagnostics = {}

    original_layout = preparation.layout_composition
    original_background = preparation._generate_daily_background
    original_decoration = preparation._apply_daily_decoration
    original_render = preparation.render_reveal_stages

    def capture_layout(composition, font, *args, **kwargs):
        resolved_fonts.append(font.identifier)
        return original_layout(composition, font, *args, **kwargs)

    def capture_background(size, identifier, registry):
        resolved_backgrounds.append(identifier)
        return original_background(size, identifier, registry)

    def capture_decoration(background, identifier, registry, tint_rgb=None, **kwargs):
        resolved_decorations.append(identifier)
        resolved_tints.append(tint_rgb)
        return original_decoration(background, identifier, registry, tint_rgb, **kwargs)

    def capture_render(*args, **kwargs):
        resolved_text_colors.append(kwargs["text_color"])
        return original_render(*args, **kwargs)

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)
    monkeypatch.setattr(preparation, "_generate_daily_background", capture_background)
    monkeypatch.setattr(preparation, "_apply_daily_decoration", capture_decoration)
    monkeypatch.setattr(preparation, "render_reveal_stages", capture_render)

    variants = _prepare_daily_image_variants(
        snapshot,
        (CompositionVisibility(),),
        configuration,
        specifications,
        chooser=chooser,
        on_diagnostics=diagnostics.__setitem__,
    )
    try:
        assert len(variants) == 2
        assert len(resolved_fonts) == len(specifications)
        assert len(resolved_backgrounds) == len(specifications)
        assert len(resolved_decorations) == len(specifications)
        assert len(resolved_tints) == len(specifications)
        assert len(resolved_text_colors) == len(specifications)
        assert len(set(resolved_fonts)) == 1
        assert len(set(resolved_backgrounds)) == 1
        assert len(set(resolved_decorations)) == 1
        assert len(set(resolved_tints)) == 1
        assert len(set(resolved_text_colors)) == 1
        assert set(chooser.counts.values()) == {1}
        assert diagnostics[ResolvedOutputSpecification("4:3", (80, 60))].qr_placement is None
        assert diagnostics[ResolvedOutputSpecification("16:10", (3840, 2400))].qr_placement is not None
        assert {
            layer.condition for layer in diagnostics[ResolvedOutputSpecification("4:3", (80, 60))].active_layers
        } == {"no-qr"}
        assert {
            layer.condition for layer in diagnostics[ResolvedOutputSpecification("16:10", (3840, 2400))].active_layers
        } == {"qr"}
    finally:
        for images in variants.values():
            for image in images:
                image.close()


@pytest.mark.parametrize(
    ("specification", "design_canvas_size"),
    [
        (ResolvedOutputSpecification("4:3", (1600, 1200)), (3200, 2400)),
        (ResolvedOutputSpecification("16:9", (1920, 1080)), (3840, 2160)),
        (ResolvedOutputSpecification("16:10", (3840, 2400)), (3840, 2400)),
        (ResolvedOutputSpecification("4:3", (1600, 1190)), (3200, 2400)),
    ],
)
def test_graphical_composition_uses_design_presentation_and_output_canvases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    specification: ResolvedOutputSpecification,
    design_canvas_size: tuple[int, int],
) -> None:
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGBA", (2, 1), (200, 20, 40, 128)) as decoration_image:
        decoration_image.save(decoration_path)
    snapshot = replace(make_snapshot("lora", source=None, attribution=None), decoration="overlay")
    configuration = _configuration(
        _FONT_REGISTRY,
        decorations={"overlay": _decoration_resource("overlay", decoration_path)},
        output_specification=specification,
        qr_enabled=False,
    )
    background_sizes: list[tuple[int, int]] = []
    decoration_sizes: list[tuple[int, int]] = []
    resize_calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
    generate_background = preparation._generate_daily_background
    apply_decoration = preparation._apply_daily_decoration
    resize = Image.Image.resize

    def capture_background(size, *args, **kwargs):
        background_sizes.append(size)
        return generate_background(size, *args, **kwargs)

    def capture_decoration(background, *args, **kwargs):
        decoration_sizes.append(background.size)
        return apply_decoration(background, *args, **kwargs)

    def capture_resize(image, size, *args, **kwargs):
        if image.size in {design_canvas_size, specification.presentation_canvas_size}:
            resize_calls.append((image.size, size))
        return resize(image, size, *args, **kwargs)

    monkeypatch.setattr(preparation, "_generate_daily_background", capture_background)
    monkeypatch.setattr(preparation, "_apply_daily_decoration", capture_decoration)
    monkeypatch.setattr(Image.Image, "resize", capture_resize)

    images = _prepare_configured_images(snapshot, (CompositionVisibility(),), configuration)
    try:
        assert background_sizes == [design_canvas_size]
        assert decoration_sizes == [design_canvas_size]
        presentation_canvas_size = specification.presentation_canvas_size
        expected_resizes = []
        if design_canvas_size != presentation_canvas_size:
            expected_resizes.append((design_canvas_size, presentation_canvas_size))
        if presentation_canvas_size != specification.requested_output_size:
            expected_resizes.append((presentation_canvas_size, specification.requested_output_size))
        assert resize_calls == expected_resizes
        assert images[0].size == specification.requested_output_size
        assert images[0].mode == "RGB"
        assert images[0].getpixel((specification.requested_output_size[0] // 2, 10)) == (255, 255, 255)
        center = images[0].getpixel(
            (specification.requested_output_size[0] // 4, specification.requested_output_size[1] // 2)
        )
        assert all(abs(actual - expected) <= 2 for actual, expected in zip(center, (227, 137, 147), strict=True))
    finally:
        for image in images:
            image.close()


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
            background.paste((0, 0, 0, 0), (0, 0, 20, 20))
            background.paste((0, 0, 0, 128), (20, 0, 40, 20))
        background.save(path)
    snapshot = replace(
        make_snapshot("lora", source=None, attribution=None),
        background="paper",
    )
    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        _FONT_REGISTRY,
        {"paper": BackgroundResource("paper", path, False)},
        output_specification=ResolvedOutputSpecification("4:3", (1600, 1200)),
    )
    try:
        image = images[0]
        assert image.getpixel((100, 100)) == color[:3]
        assert (0, 0, 0) in image.get_flattened_data()
        if mode == "RGBA":
            assert image.getpixel((5, 5)) == (255, 255, 255)
            assert image.getpixel((30, 5)) == (127, 127, 127)
    finally:
        for image in images:
            image.close()


def test_background_cover_scaling_crops_center_of_wide_source(tmp_path: Path) -> None:
    path = tmp_path / "wide.png"
    with Image.new("RGB", (400, 100), (0, 0, 0)) as background:
        background.paste((255, 0, 0), (0, 0, 100, 100))
        background.paste((0, 255, 0), (100, 0, 300, 100))
        background.paste((0, 0, 255), (300, 0, 400, 100))
        background.save(path)
    snapshot = replace(make_snapshot("lora", source=None, attribution=None), background="wide")
    configuration = _configuration(
        _FONT_REGISTRY,
        backgrounds={"wide": BackgroundResource("wide", path, False)},
        output_specification=ResolvedOutputSpecification("4:3", (1600, 1200)),
        qr_enabled=False,
    )

    images = _prepare_configured_images(
        snapshot,
        (CompositionVisibility(),),
        configuration,
    )
    try:
        image = images[0]
        assert image.getpixel((10, 10)) == (0, 255, 0)
        assert image.getpixel((1590, 10)) == (0, 255, 0)
        assert image.getpixel((10, 1190)) == (0, 255, 0)
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
        {"overlay": _decoration_resource("overlay", decoration_path)},
        insets=PresentationInsets(2400, 160, 1800, 120),
        output_specification=ResolvedOutputSpecification("4:3", (1600, 1200)),
        min_font_size=16,
        max_font_size=24,
    )
    try:
        assert all(image.mode == "RGB" and image.size == (1600, 1200) for image in images)
        assert images[0].getpixel((10, 10)) == (200, 20, 40)
        for image in images[1:]:
            assert image.crop((1467, 1067, 1590, 1190)).tobytes() == images[0].crop((1467, 1067, 1590, 1190)).tobytes()
        assert images[0].getpixel((1467, 1067)) == (255, 255, 255)
        assert images[0].getpixel((1479, 1079)) == (0, 0, 0)
        assert snapshot.decoration == "overlay"
    finally:
        for image in images:
            image.close()


def test_explicit_presentation_overrides_precede_entry_and_decoration_preferences() -> None:
    decoration = DecorationResource(
        "frame",
        (DecorationLayerResource(Path("/unused-layer.png"), "contain", tintable=True),),
        False,
        tintable=True,
        qr_ready=False,
    )
    configuration = _configuration(
        {**_MULTI_FACE_REGISTRY, "lora-alt": FontResource("lora-alt", _LORA, bundled=True)},
        backgrounds={"paper": BackgroundResource("paper", Path("/unused-paper.png"), False)},
        decorations={"frame": decoration},
        qr_enabled=False,
    )
    snapshot = replace(
        make_snapshot("lora-alt", metadata={"font_faces": {"quotation": "regular"}}),
        background="none",
        decoration="none",
        text_color=("black",),
        decoration_color=("black",),
    )

    choices = preparation._resolve_presentation_choices(
        snapshot,
        configuration,
        Random(1),
        force_white_background=False,
        forced_decoration_tint=None,
        overrides=PresentationOverrides(
            font="lora",
            font_faces={"attribution": "italic"},
            background="paper",
            decoration="frame",
            text_color="burnt-orange",
            tint="blue",
            style="left-aligned",
            qr_enabled=True,
        ),
    )

    assert choices.fonts["quotation"].identifier == "lora"
    assert choices.fonts["attribution"].identifier == "lora:italic"
    assert choices.background_identifier == "paper"
    assert choices.decoration_identifier == "frame"
    assert choices.text_color == (198, 90, 32)
    assert choices.decoration_tint == (0, 0, 255)
    assert choices.presentation_style == "left-aligned"
    assert choices.qr_enabled is True
    assert choices.strict_background is True
    assert choices.strict_decoration is True
    assert choices.fonts["quotation"].identifier == "lora"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (PresentationOverrides(font="missing-font"), "explicit font"),
        (PresentationOverrides(font_faces={"quotation": "bold"}), "explicit quotation face"),
        (PresentationOverrides(background="missing-background"), "explicit background"),
        (PresentationOverrides(decoration="missing-decoration"), "explicit decoration"),
        (PresentationOverrides(text_color="missing-color"), "explicit text color"),
        (PresentationOverrides(tint="missing-color"), "explicit decoration tint color"),
        (PresentationOverrides(style="unsupported"), "unsupported presentation style"),
    ],
)
def test_unavailable_explicit_presentation_overrides_fail_without_fallback(
    overrides: PresentationOverrides, message: str
) -> None:
    configuration = _configuration(_MULTI_FACE_REGISTRY)

    with pytest.raises(DailyImagePreparationError, match=message):
        preparation._resolve_presentation_choices(
            make_snapshot("lora"),
            configuration,
            Random(1),
            force_white_background=False,
            forced_decoration_tint=None,
            overrides=overrides,
        )


def test_explicit_tint_does_not_make_non_tintable_decoration_tintable() -> None:
    decoration = DecorationResource(
        "untinted",
        (DecorationLayerResource(Path("/unused-layer.png"), "contain", tintable=True),),
        False,
        tintable=False,
    )
    configuration = _configuration(_FONT_REGISTRY, decorations={"untinted": decoration})

    choices = preparation._resolve_presentation_choices(
        make_snapshot("lora"),
        configuration,
        Random(1),
        force_white_background=False,
        forced_decoration_tint=None,
        overrides=PresentationOverrides(decoration="untinted", tint="blue"),
    )

    assert choices.decoration_tint is None


def test_background_preferences_precede_decoration_preferences_for_both_colors() -> None:
    decoration = DecorationResource(
        "frame",
        (DecorationLayerResource(Path("/unused-layer.png"), "contain", tintable=True),),
        False,
        text_color=("blue",),
        decoration_color=("blue",),
        tintable=True,
    )
    background = BackgroundResource(
        "paper",
        None,
        False,
        text_color=("burnt-orange",),
        decoration_color=("burnt-orange",),
    )
    configuration = _configuration(
        _FONT_REGISTRY,
        backgrounds={"paper": background},
        decorations={"frame": decoration},
    )

    text_color = preparation._resolve_text_color(
        configuration, make_snapshot("lora"), decoration, background, Random(1)
    )
    decoration_color = preparation._resolve_decoration_tint(
        configuration,
        make_snapshot("lora"),
        decoration,
        Random(1),
        decoration.layers,
        background=background,
    )

    assert text_color == (198, 90, 32)
    assert decoration_color == (198, 90, 32)


def test_content_color_preferences_override_background_and_decoration() -> None:
    decoration = DecorationResource(
        "frame",
        (DecorationLayerResource(Path("/unused-layer.png"), "contain", tintable=True),),
        False,
        text_color=("blue",),
        decoration_color=("blue",),
        tintable=True,
    )
    background = BackgroundResource(
        "paper",
        None,
        False,
        text_color=("burnt-orange",),
        decoration_color=("burnt-orange",),
    )
    configuration = _configuration(
        _FONT_REGISTRY,
        backgrounds={"paper": background},
        decorations={"frame": decoration},
    )
    snapshot = replace(make_snapshot("lora"), text_color=("black",), decoration_color=("blue",))

    assert preparation._resolve_text_color(configuration, snapshot, decoration, background, Random(1)) == (0, 0, 0)
    assert preparation._resolve_decoration_tint(
        configuration,
        snapshot,
        decoration,
        Random(1),
        decoration.layers,
        background=background,
    ) == (0, 0, 255)


def test_unusable_background_color_preferences_fall_through_to_decoration_or_global_pool(caplog) -> None:
    decoration = DecorationResource(
        "frame",
        (DecorationLayerResource(Path("/unused-layer.png"), "contain", tintable=True),),
        False,
        text_color=("blue",),
        tintable=True,
    )
    background = BackgroundResource(
        "paper",
        None,
        False,
        text_color=("not-in-palette",),
        decoration_color=("not-in-palette",),
    )
    configuration = replace(
        _configuration(
            _FONT_REGISTRY,
            backgrounds={"paper": background},
            decorations={"frame": decoration},
        ),
        default_text_colors=("burnt-orange",),
        default_decoration_colors=("blue",),
    )
    snapshot = make_snapshot("lora")

    text_color = preparation._resolve_text_color(configuration, snapshot, decoration, background, Random(1))
    decoration_color = preparation._resolve_decoration_tint(
        configuration,
        snapshot,
        decoration,
        Random(1),
        decoration.layers,
        background=background,
    )

    assert text_color == (0, 0, 255)
    assert decoration_color == (0, 0, 255)
    assert "selected background" in caplog.text


def test_forced_qr_still_obeys_decoration_readiness(tmp_path: Path) -> None:
    layer_path = tmp_path / "frame.png"
    with Image.new("RGBA", (8, 8), (0, 0, 0, 0)) as layer:
        layer.save(layer_path)
    decoration = DecorationResource(
        "frame",
        (DecorationLayerResource(layer_path, "contain", tintable=False),),
        False,
        tintable=False,
        qr_ready=False,
    )
    configuration = _configuration(
        _FONT_REGISTRY,
        decorations={"frame": decoration},
        output_specification=ResolvedOutputSpecification("16:10", (320, 200)),
        qr_enabled=False,
    )
    diagnostics = {}

    variants = preparation.prepare_daily_images(
        replace(
            make_snapshot("lora", source=None, attribution=None),
            quotation_text="A",
            quotation_identity="A",
        ),
        (CompositionVisibility(),),
        configuration,
        (ResolvedOutputSpecification("16:10", (320, 200)),),
        overrides=PresentationOverrides(decoration="frame", qr_enabled=True),
        on_diagnostics=diagnostics.__setitem__,
    )
    try:
        result = diagnostics[ResolvedOutputSpecification("16:10", (320, 200))]
        assert result.qr_placement is None
        assert "not marked qr_ready" in result.qr_unavailable_reason
    finally:
        for images in variants.values():
            for image in images:
                image.close()


@pytest.mark.parametrize("reason", ["policy", "decoration"])
def test_intentional_qr_disabling_skips_placement_without_warning(monkeypatch, caplog, reason: str) -> None:
    snapshot = replace(
        make_snapshot("lora"),
        decoration="frame" if reason == "decoration" else None,
    )
    decoration = _decoration_resource("frame", Path("/unused.png"), qr_ready=reason != "decoration")
    configuration = _configuration(
        _FONT_REGISTRY,
        decorations={"frame": decoration},
        qr_enabled=reason != "policy",
    )
    monkeypatch.setattr(
        preparation,
        "resolve_qr_placement",
        lambda *_: pytest.fail("disabled QR must not resolve placement"),
    )
    images = _prepare_configured_images(snapshot, (CompositionVisibility(),), configuration)
    try:
        assert len(images) == 1
        assert "QR generation is disabled" not in caplog.text
    finally:
        for image in images:
            image.close()


def test_invalid_qr_placement_warns_before_artwork_and_preserves_decoration(monkeypatch, caplog) -> None:
    snapshot = replace(make_snapshot("lora"), decoration="frame")
    decoration = _decoration_resource(
        "frame",
        Path("/unused.png"),
        qr_positioning={"qr_from_left": -1},
    )
    configuration = _configuration(_FONT_REGISTRY, decorations={"frame": decoration})
    events: list[str] = []
    resolve_placement = preparation.resolve_qr_placement
    apply_decoration = preparation._apply_daily_decoration

    def record_placement(*args, **kwargs):
        events.append("placement")
        return resolve_placement(*args, **kwargs)

    def record_artwork(*args, **kwargs):
        events.append("artwork")
        return apply_decoration(*args, **kwargs)

    monkeypatch.setattr(preparation, "resolve_qr_placement", record_placement)
    monkeypatch.setattr(preparation, "_apply_daily_decoration", record_artwork)
    monkeypatch.setattr(
        preparation,
        "render_qr_code",
        lambda *_args, **_kwargs: pytest.fail("suppressed QR must not be rasterized"),
    )

    images = _prepare_configured_images(snapshot, resolve_reveal_stages(snapshot), configuration)
    try:
        assert len(images) == 3
        assert events == ["placement", "artwork"]
        assert snapshot.decoration == "frame"
        assert "QR generation is disabled for this preparation" in caplog.text
        assert "qr_from_left must be a nonnegative integer" in caplog.text
    finally:
        for image in images:
            image.close()


def test_insufficient_output_pixels_warn_and_keep_literary_preparation(caplog) -> None:
    snapshot = make_snapshot("lora", source=None, attribution=None)
    configuration = _configuration(
        _FONT_REGISTRY,
        output_specification=ResolvedOutputSpecification("4:3", (80, 60)),
        insets=PresentationInsets(0, 0, 0, 0),
        min_font_size=1,
        max_font_size=1,
    )

    images = _prepare_configured_images(snapshot, (CompositionVisibility(),), configuration)
    try:
        assert len(images) == 1
        assert images[0].size == (80, 60)
        assert "complete 41-module QR footprint" in caplog.text
        assert snapshot.quotation_text == "A small thought, carefully kept."
    finally:
        for image in images:
            image.close()


def test_decoration_overlays_background_with_rgba_transparency_before_text(tmp_path: Path) -> None:
    background_path = tmp_path / "paper.png"
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGB", (1600, 1200), (80, 120, 160)) as background:
        background.save(background_path)
    with Image.new("RGBA", (1600, 1200), (200, 20, 40, 128)) as decoration:
        decoration.paste((200, 20, 40, 0), (0, 0, 20, 20))
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
        {"overlay": _decoration_resource("overlay", decoration_path)},
        output_specification=ResolvedOutputSpecification("4:3", (1600, 1200)),
    )
    try:
        image = images[0]
        assert image.mode == "RGB"
        assert image.getpixel((10, 10)) == (80, 120, 160)
        assert all(
            abs(actual - expected) <= 1
            for actual, expected in zip(image.getpixel((50, 50)), (140, 70, 100), strict=True)
        )
    finally:
        for image in images:
            image.close()


@pytest.mark.parametrize(
    ("specification", "cover_sample", "top_sample"),
    [
        (ResolvedOutputSpecification("4:3", (1600, 1200)), (40, 80, 120), (255, 255, 0)),
        (ResolvedOutputSpecification("16:9", (1920, 1080)), (255, 0, 0), (40, 80, 120)),
        (ResolvedOutputSpecification("16:10", (1920, 1200)), (255, 0, 0), (255, 255, 0)),
    ],
)
def test_cover_decoration_prepares_all_aspects_and_reveal_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    specification: ResolvedOutputSpecification,
    cover_sample: tuple[int, int, int],
    top_sample: tuple[int, int, int],
) -> None:
    artwork_path = tmp_path / "cover.png"
    with Image.new("RGB", (3840, 2400), (40, 80, 120)) as artwork:
        artwork.paste((255, 0, 0), (0, 0, 320, 2400))
        artwork.paste((0, 0, 255), (3520, 0, 3840, 2400))
        artwork.paste((255, 255, 0), (0, 0, 3840, 120))
        artwork.paste((255, 0, 255), (0, 2280, 3840, 2400))
        artwork.save(artwork_path)

    decoration = DecorationResource(
        "cover",
        (DecorationLayerResource(artwork_path, "cover", tintable=False),),
        False,
        qr_positioning={"qr_from_left": 20, "qr_from_top": 20},
    )
    snapshot = replace(make_snapshot("lora"), decoration="cover")
    stages = resolve_reveal_stages(snapshot)
    layouts = []
    original_layout = preparation.layout_composition

    def capture_layout(*args, **kwargs):
        layout = original_layout(*args, **kwargs)
        layouts.append(layout)
        return layout

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)
    images = prepare_daily_images(
        snapshot,
        stages,
        _FONT_REGISTRY,
        decoration_registry={"cover": decoration},
        output_specification=specification,
    )
    try:
        assert len(images) == len(stages) == 3
        assert all(image.size == specification.requested_output_size for image in images)
        assert len(layouts) == 1
        assert layouts[0].quotation.bounds[2] <= specification.presentation_canvas_size[0]
        assert layouts[0].quotation.bounds[3] <= specification.presentation_canvas_size[1]

        cover_point = (50, specification.requested_output_size[1] // 2)
        top_point = (specification.requested_output_size[0] // 2, 40)
        for image in images:
            assert image.getpixel(cover_point) == cover_sample
            assert image.getpixel(top_point) == top_sample
            assert image.getpixel((10, 10)) == (255, 255, 255)
        assert all(image.getpixel(cover_point) == images[0].getpixel(cover_point) for image in images)

        with images[0].crop(layouts[0].quotation.bounds) as quotation:
            assert any(pixel == (0, 0, 0) for pixel in quotation.get_flattened_data())
    finally:
        for image in images:
            image.close()


def test_decoration_color_preference_resolves_during_preparation_and_preserves_alpha(tmp_path: Path) -> None:
    decoration_path = tmp_path / "overlay.png"
    with Image.new("RGBA", _IMAGE_SIZE, (20, 40, 60, 255)) as decoration:
        decoration.paste((0, 0, 0, 0), (0, 0, 256, 200))
        decoration.paste((255, 255, 255, 128), (256, 0, 512, 200))
        decoration.paste((0, 0, 0, 255), (512, 0, 768, 200))
        decoration.paste((40, 80, 120, 128), (768, 0, 1024, 200))
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
        decoration_registry={"overlay": _decoration_resource("overlay", decoration_path, tintable=True)},
    )
    try:
        for image in images:
            assert image.getpixel((100, 100)) == (255, 255, 255)
            assert image.getpixel((600, 100)) == (198, 90, 32)
            assert image.getpixel((300, 100)) != (255, 255, 255)
            assert image.getpixel((900, 100)) != (40, 80, 120)
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
        decoration_registry={"overlay": _decoration_resource("overlay", decoration_path, tintable=True)},
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


def test_packaged_background_layers_composite_in_declaration_order_with_alpha(tmp_path: Path) -> None:
    base_path = tmp_path / "base.png"
    overlay_path = tmp_path / "overlay.png"
    with Image.new("RGB", (4, 2), (240, 20, 10)) as base:
        base.save(base_path)
    with Image.new("RGBA", (4, 2), (0, 0, 0, 0)) as overlay:
        overlay.putpixel((1, 0), (0, 0, 255, 128))
        overlay.save(overlay_path)
    resource = BackgroundResource(
        "layered",
        None,
        False,
        (
            BackgroundLayerResource(base_path, "cover"),
            BackgroundLayerResource(overlay_path, "cover"),
        ),
    )

    background = preparation._generate_daily_background((4, 2), "layered", {"layered": resource})
    try:
        assert background.getpixel((0, 0)) == (240, 20, 10)
        assert all(
            abs(actual - expected) <= 1
            for actual, expected in zip(background.getpixel((1, 0)), (120, 10, 133), strict=True)
        )
    finally:
        background.close()


def test_packaged_background_contain_centres_artwork_on_paper_white(tmp_path: Path) -> None:
    image_path = tmp_path / "portrait.png"
    with Image.new("RGBA", (2, 1), (10, 20, 240, 255)) as source:
        source.save(image_path)
    resource = BackgroundResource(
        "contained",
        None,
        False,
        (BackgroundLayerResource(image_path, "contain"),),
    )

    background = preparation._generate_daily_background((4, 4), "contained", {"contained": resource})
    try:
        assert background.getpixel((0, 0)) == (255, 255, 255)
        assert background.getpixel((1, 1)) == (10, 20, 240)
        assert background.getpixel((1, 2)) == (10, 20, 240)
        assert background.getpixel((0, 3)) == (255, 255, 255)
    finally:
        background.close()


def test_background_layer_cover_uses_the_same_transform_as_decoration(tmp_path: Path) -> None:
    path = tmp_path / "wide.png"
    with Image.new("RGBA", (8, 2), (0, 0, 0, 255)) as source:
        source.putpixel((3, 0), (255, 0, 0, 255))
        source.putpixel((4, 1), (0, 0, 255, 255))
        source.save(path)
    background_resource = BackgroundResource(
        "cover",
        None,
        False,
        (BackgroundLayerResource(path, "cover"),),
    )
    decoration_resource = DecorationResource(
        "cover",
        (DecorationLayerResource(path, "cover", tintable=False),),
        False,
    )

    background = preparation._generate_daily_background((4, 4), "cover", {"cover": background_resource})
    decoration_background = Image.new("RGB", (4, 4), "white")
    try:
        preparation._apply_daily_decoration(decoration_background, "cover", {"cover": decoration_resource})
        assert background.tobytes() == decoration_background.tobytes()
    finally:
        background.close()
        decoration_background.close()


def test_decoration_contain_scaling_centres_transparent_portrait(tmp_path: Path) -> None:
    path = tmp_path / "portrait.png"
    with Image.new("RGBA", (2, 4), (220, 40, 20, 128)) as source:
        source.save(path)
    background = Image.new("RGB", (8, 4), (80, 120, 160))

    composed = preparation._apply_daily_decoration(
        background,
        "portrait",
        {"portrait": _decoration_resource("portrait", path)},
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
            insets=PresentationInsets(1882, 1882, 1058, 1058),
            min_font_size=24,
            max_font_size=28,
        )

    assert snapshot == original_snapshot


def test_non_snapshot_input_fails_clearly() -> None:
    with pytest.raises(DailyImagePreparationError, match="DailySnapshot"):
        prepare_daily_images(None, (CompositionVisibility(),), _FONT_REGISTRY)  # type: ignore[arg-type]

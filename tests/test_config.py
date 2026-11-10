from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import time
from importlib.resources import files
from pathlib import Path
from zipfile import Path as ZipPath
from zipfile import ZipFile

import pytest
import yaml
from PIL import Image

from refrain import (
    ApplicationConfigurationError,
    BackgroundResource,
    DecorationLayerResource,
    DecorationResource,
    PresentationInsets,
    load_application_config,
    load_background_image,
    load_decoration_layer_image,
)


def configuration_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "general": {},
        "content": {"directory": "content"},
        "display": {"backends": [{"type": "window"}]},
        "layout": {
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 28, "max_font_size": 100},
        },
    }
    data.update(overrides)
    return data


def write_config(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_asset_manifest(directory: Path, name: str, data: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def diagnostic_fields(path: Path) -> tuple[str, ...]:
    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(path)
    assert all(str(path) in str(diagnostic) for diagnostic in error.value.diagnostics)
    return tuple(diagnostic.field for diagnostic in error.value.diagnostics)


def background_configuration(**settings: object) -> dict[str, object]:
    data = configuration_data()
    data["layout"]["backgrounds"] = settings
    return data


def decoration_configuration(**settings: object) -> dict[str, object]:
    data = configuration_data()
    data["layout"]["decorations"] = settings
    return data


def test_bundled_background_registry_and_plain_default(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    assert set(config.backgrounds) == {
        "aged-paper",
        "canvas",
        "cloth",
        "drafting-grid",
        "handmade-paper",
        "hex",
        "isometric-grid",
        "limestone",
        "recursive-squares",
        "vellum",
    }
    assert config.default_backgrounds == ("none",)
    assert all(resource.bundled for resource in config.backgrounds.values())
    assert not any(record.levelno >= 30 and "background" in record.message for record in caplog.records)
    for identifier, resource in config.backgrounds.items():
        assert resource.identifier == identifier
        assert resource.path.name == f"{identifier}.png"
        with load_background_image(resource) as image:
            assert image.size == (3840, 2400)
            assert image.mode in {"RGB", "RGBA"}
    with pytest.raises(TypeError):
        config.backgrounds["other"] = config.backgrounds["canvas"]


def test_builtin_palette_custom_colors_and_black_text_default(tmp_path: Path) -> None:
    data = configuration_data()
    data["palette"] = {"red": "#C82F32", "burnt-orange": "#C65A20"}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert dict(config.palette) == {
        "black": "#000000",
        "white": "#FFFFFF",
        "red": "#C82F32",
        "yellow": "#FFFF00",
        "blue": "#0000FF",
        "green": "#00FF00",
        "burnt-orange": "#C65A20",
    }
    assert config.default_text_colors == ("black",)
    assert config.default_decoration_colors == ("black",)


def test_decoration_color_pool_uses_shared_palette_and_distinct_members(tmp_path: Path, caplog) -> None:
    data = configuration_data()
    data["palette"] = {"sage-green": "#718C23", "terracotta": "#C65A20"}
    data["layout"]["decorations"] = {
        "default": ["none"],
        "colors": ["sage-green", "missing", "sage-green", "terracotta", None],
    }

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_decoration_colors == ("sage-green", "terracotta")
    assert "palette identifier 'missing' is unavailable" in caplog.text
    assert "duplicates palette identifier 'sage-green'" in caplog.text
    assert "layout.decorations.colors[4]" in caplog.text


@pytest.mark.parametrize("pool", [None, [], "bad", ["missing"], ["", None]])
def test_unusable_decoration_color_pool_falls_back_to_black(tmp_path: Path, caplog, pool: object) -> None:
    data = configuration_data()
    data["layout"]["decorations"] = {"colors": pool}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_decoration_colors == ("black",)
    assert "layout.decorations.colors" in caplog.text
    assert "using ['black']" in caplog.text


def test_invalid_palette_definitions_are_warned_and_ignored(tmp_path: Path, caplog) -> None:
    data = configuration_data()
    data["palette"] = {"invalid id": "#123456", "bad-hex": "#12345g", "red": "#123"}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert "invalid id" not in config.palette
    assert "bad-hex" not in config.palette
    assert config.palette["red"] == "#FF0000"
    assert "palette.invalid id" in caplog.text
    assert "quoted six-digit #RRGGBB" in caplog.text


def test_text_color_pool_filters_unavailable_and_duplicate_members(tmp_path: Path, caplog) -> None:
    data = configuration_data()
    data["palette"] = {"burnt-orange": "#C65A20"}
    data["layout"]["text"]["colors"] = ["burnt-orange", "missing", "burnt-orange", None, "blue"]

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_text_colors == ("burnt-orange", "blue")
    assert "palette identifier 'missing' is unavailable" in caplog.text
    assert "duplicates palette identifier 'burnt-orange'" in caplog.text


@pytest.mark.parametrize("pool", [None, [], "bad", ["missing"], ["", None]])
def test_unusable_text_color_pool_falls_back_to_black(tmp_path: Path, caplog, pool: object) -> None:
    data = configuration_data()
    data["layout"]["text"]["colors"] = pool

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_text_colors == ("black",)
    assert "layout.text.colors" in caplog.text
    assert "using ['black']" in caplog.text


def test_global_role_face_preferences_and_packaged_italic_default(tmp_path: Path) -> None:
    data = configuration_data()
    data["layout"]["fonts"] = {
        "default": ["lora"],
        "font_faces": {"quotation": "regular", "attribution": "italic"},
    }
    config = load_application_config(write_config(tmp_path / "config.yaml", data))
    assert dict(config.font_faces) == {"quotation": "regular", "attribution": "italic"}

    packaged_config = Path(str(files("refrain").joinpath("config.default.yaml")))
    packaged = load_application_config(packaged_config)
    assert dict(packaged.font_faces) == {"attribution": "italic"}
    assert packaged.default_decoration_colors == ("black",)
    assert {"regular", "italic"} <= set(packaged.fonts["lora"].faces)
    assert packaged.fonts["lora"].faces["italic"].name == "Lora-Italic.ttf"


@pytest.mark.parametrize(
    "preferences",
    [None, [], "bad", {"byline": "italic"}, {"source": None}, {"quotation": ""}, {"attribution": "bad face"}],
)
def test_invalid_global_role_face_preferences_are_warned_and_ignored(
    tmp_path: Path, preferences: object, caplog
) -> None:
    data = configuration_data()
    data["layout"]["fonts"] = {"default": ["lora"], "font_faces": preferences}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.font_faces == {}
    assert "layout.fonts.font_faces" in caplog.text


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_custom_background_discovery_and_modes(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "assets" / "backgrounds" / "nested" / "paper.png"
    path.parent.mkdir(parents=True)
    Image.new(mode, (31, 17)).save(path)
    data = background_configuration(default=["paper"])

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.backgrounds["paper"] == BackgroundResource("paper", path, False)
    assert config.default_backgrounds == ("paper",)
    with load_background_image(config.backgrounds["paper"]) as image:
        assert image.mode == mode
        assert image.getpixel((0, 0)) == ((0, 0, 0) if mode == "RGB" else (0, 0, 0, 0))


@pytest.mark.parametrize("kind", ["jpeg", "palette", "gray", "animation", "corrupt", "truncated"])
def test_invalid_backgrounds_excluded_independently(tmp_path: Path, kind: str, caplog) -> None:
    backgrounds = tmp_path / "assets" / "backgrounds"
    backgrounds.mkdir(parents=True)
    bad_path = backgrounds / "bad.png"
    good_path = backgrounds / "good.png"
    Image.new("RGB", (1600, 1200)).save(good_path)
    if kind == "jpeg":
        Image.new("RGB", (1600, 1200)).save(bad_path, format="JPEG")
    elif kind in {"palette", "gray"}:
        Image.new("P" if kind == "palette" else "L", (1600, 1200)).save(bad_path)
    elif kind == "animation":
        Image.new("RGBA", (1600, 1200)).save(
            bad_path, save_all=True, append_images=[Image.new("RGBA", (1600, 1200), "red")], duration=100
        )
    elif kind == "corrupt":
        bad_path.write_bytes(b"not an image")
    elif kind == "truncated":
        bad_path.write_bytes(good_path.read_bytes()[:100])
    data = background_configuration(default=["bad", "good"])

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert "bad" not in config.backgrounds
    assert "good" in config.backgrounds
    assert config.default_backgrounds == ("good",)
    assert "assets.background.bad" in caplog.text
    assert "excluded" in caplog.text


@pytest.mark.parametrize(
    "identifier",
    [
        "none",
        "aged-paper",
        "canvas",
        "cloth",
        "drafting-grid",
        "handmade-paper",
        "hex",
        "isometric-grid",
        "limestone",
        "recursive-squares",
        "vellum",
    ],
)
def test_reserved_background_identifiers_cannot_be_overridden(tmp_path: Path, identifier: str, caplog) -> None:
    asset_path = tmp_path / "assets" / "backgrounds" / f"{identifier}.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6)).save(asset_path)
    data = background_configuration()

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    if identifier == "none":
        assert identifier not in config.backgrounds
    else:
        assert config.backgrounds[identifier].bundled
    assert "reserved" in caplog.text
    assert config.default_backgrounds == ("none",)


@pytest.mark.parametrize(
    "available",
    [
        None,
        [],
        "bad",
        {None: "bad.png"},
        {1: "bad.png"},
        {"": "bad.png"},
        {" ": "bad.png"},
        {"custom": None},
        {"custom": ""},
        {"custom": " "},
        {"custom": 1},
    ],
)
def test_malformed_background_registrations_warn(tmp_path: Path, available: object, caplog) -> None:
    data = background_configuration(available=available)

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert set(config.backgrounds) == {
        "aged-paper",
        "canvas",
        "cloth",
        "drafting-grid",
        "handmade-paper",
        "hex",
        "isometric-grid",
        "limestone",
        "recursive-squares",
        "vellum",
    }
    assert "layout.backgrounds.available" in caplog.text


def test_default_background_pool_deduplicates_and_excludes_invalid_values(tmp_path: Path, caplog) -> None:
    data = background_configuration(default=["canvas", "none", "canvas", None, False, "", " ", "Canvas", "hex", "none"])

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_backgrounds == ("canvas", "none", "hex")
    assert "background identifier 'Canvas' is unavailable" in caplog.text
    assert "must be a valid background identifier" in caplog.text


@pytest.mark.parametrize("pool", [None, [], {}, "canvas", False, ["missing"], ["", None, " "]])
def test_unusable_background_pool_falls_back_to_none(tmp_path: Path, pool: object, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", background_configuration(default=pool)))

    assert config.default_backgrounds == ("none",)
    assert "layout.backgrounds.default" in caplog.text
    assert "has no usable members; using ['none']" in caplog.text


@pytest.mark.parametrize("section", [None, [], "bad"])
def test_malformed_background_section_warns_and_uses_default(tmp_path: Path, section: object, caplog) -> None:
    data = configuration_data()
    data["layout"]["backgrounds"] = section

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_backgrounds == ("none",)
    assert "layout.backgrounds: must be a mapping" in caplog.text


def test_unknown_background_settings_warn(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", background_configuration(unknown=True)))

    assert config.default_backgrounds == ("none",)
    assert "layout.backgrounds.unknown" in caplog.text


def test_background_loader_revalidates_resource_changes(tmp_path: Path) -> None:
    path = tmp_path / "paper.png"
    Image.new("RGB", (1600, 1200), "red").save(path)
    resource = BackgroundResource("paper", path, False)
    image = load_background_image(resource)
    Image.new("RGB", (1600, 1200), "blue").save(path)
    with load_background_image(resource) as changed_image:
        assert changed_image.getpixel((0, 0)) == (0, 0, 255)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    image.close()
    Image.new("L", (1600, 1200)).save(path)
    with pytest.raises(ValueError, match="mode must be RGB or RGBA"):
        load_background_image(resource)
    path.unlink()
    with pytest.raises(OSError):
        load_background_image(resource)


def test_background_loader_supports_non_filesystem_package_resources(tmp_path: Path) -> None:
    image_path = tmp_path / "paper.png"
    Image.new("RGBA", (1600, 1200), (15, 30, 45, 128)).save(image_path)
    archive_path = tmp_path / "resources.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.write(image_path, "assets/backgrounds/paper.png")
    with ZipFile(archive_path) as archive:
        resource = BackgroundResource("paper", ZipPath(archive, "assets/backgrounds/paper.png"), True)
        image = load_background_image(resource)

    assert image.getpixel((0, 0)) == (15, 30, 45, 128)
    image.close()


def test_unreadable_background_excluded_with_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    background_path = tmp_path / "assets" / "backgrounds" / "paper.png"
    background_path.parent.mkdir(parents=True)
    Image.new("RGB", (1600, 1200)).save(background_path)
    config_path = write_config(tmp_path / "config.yaml", background_configuration(default=["paper"]))
    original_open = Path.open

    def deny_background_read(path: Path, *args, **kwargs):
        if path == background_path:
            raise PermissionError("background read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_background_read)

    config = load_application_config(config_path)

    assert "paper" not in config.backgrounds
    assert config.default_backgrounds == ("none",)
    assert "assets.background.paper" in caplog.text
    assert "background read denied" in caplog.text


def test_bundled_decoration_registry_and_plain_default(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    identifiers = {"ethereal", "hex", "lower-flourish", "simple-border", "top-bottom-borders"}
    assert set(config.decorations) == identifiers
    assert config.default_decorations == ("none",)
    assert "none" not in config.decorations
    assert all(resource.bundled for resource in config.decorations.values())
    assert all(
        resource.font is None and resource.background is None and resource.presentation_insets is None
        for resource in config.decorations.values()
    )
    assert not any(record.levelno >= 30 and "decoration" in record.message for record in caplog.records)
    for identifier, resource in config.decorations.items():
        assert resource.identifier == identifier
        assert resource.layers[0].image.name == f"{identifier}.png"
        with load_decoration_layer_image(resource.layers[0]) as image:
            assert image.size == (1600, 1200)
            assert image.mode in {"RGB", "RGBA"}
    with pytest.raises(TypeError):
        config.decorations["other"] = config.decorations["hex"]


def test_custom_decoration_manifest_and_metadata(tmp_path: Path) -> None:
    package = tmp_path / "assets" / "decorations" / "custom-flourish"
    path = package / "flourish.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (29, 17), (12, 34, 56, 128)).save(path)
    write_asset_manifest(
        package,
        "decoration.yaml",
        {
            "format": 1,
            "id": "custom-flourish",
            "layers": [{"image": "flourish.png", "method": "contain"}],
            "presentation_insets": {"left": 384, "right": 768, "top": 432, "bottom": 432},
            "font": "lora",
            "text_color": ["black", "burnt-orange"],
            "background": "none",
        },
    )
    data = decoration_configuration(
        default=["custom-flourish"],
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.decorations["custom-flourish"] == DecorationResource(
        "custom-flourish",
        (DecorationLayerResource(path, "contain"),),
        False,
        PresentationInsets(384, 768, 432, 432),
        "lora",
        "none",
        text_color=("black", "burnt-orange"),
    )
    assert config.default_decorations == ("custom-flourish",)


@pytest.mark.parametrize("kind", ["unsupported-mode", "animation", "corrupt", "missing"])
def test_invalid_decorations_are_excluded_independently(tmp_path: Path, kind: str, caplog) -> None:
    decorations = tmp_path / "assets" / "decorations"
    bad_package = decorations / "bad-package"
    good_package = decorations / "good-package"
    bad_path = bad_package / "bad.png"
    good_path = good_package / "good.png"
    good_path.parent.mkdir(parents=True)
    Image.new("RGBA", (37, 21)).save(good_path)
    if kind == "unsupported-mode":
        bad_path.parent.mkdir(parents=True)
        Image.new("L", (1600, 1200)).save(bad_path)
    elif kind == "animation":
        bad_path.parent.mkdir(parents=True)
        Image.new("RGBA", (1600, 1200)).save(
            bad_path, save_all=True, append_images=[Image.new("RGBA", (1600, 1200), "red")], duration=100
        )
    elif kind == "corrupt":
        bad_path.parent.mkdir(parents=True)
        bad_path.write_bytes(b"not an image")
    write_asset_manifest(
        bad_package,
        "decoration.yaml",
        {
            "format": 1,
            "id": "bad",
            "layers": [{"image": "missing.png" if kind == "missing" else "bad.png", "method": "contain"}],
        },
    )
    write_asset_manifest(
        good_package,
        "decoration.yaml",
        {"format": 1, "id": "good", "layers": [{"image": "good.png", "method": "contain"}]},
    )
    data = decoration_configuration(
        default=["bad", "good"],
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert "bad" not in config.decorations
    assert "good" in config.decorations
    assert config.default_decorations == ("good",)
    assert "decoration.yaml.layers[0]" in caplog.text
    if kind == "missing":
        assert "resource path is missing" in caplog.text
    assert "excluded" in caplog.text


def test_bad_decoration_region_excludes_only_its_registration(tmp_path: Path, caplog) -> None:
    decorations = tmp_path / "assets" / "decorations"
    (decorations / "bad-region").mkdir(parents=True)
    (decorations / "valid").mkdir(parents=True)
    Image.new("RGBA", (1600, 1200)).save(decorations / "bad-region" / "overlay.png")
    Image.new("RGBA", (1600, 1200)).save(decorations / "valid" / "overlay.png")
    write_asset_manifest(
        decorations / "bad-region",
        "decoration.yaml",
        {
            "format": 1,
            "id": "bad-region",
            "layers": [{"image": "overlay.png", "method": "contain"}],
            "presentation_insets": {"left": 3840, "right": 0, "top": 0, "bottom": 0},
        },
    )
    write_asset_manifest(
        decorations / "valid",
        "decoration.yaml",
        {"format": 1, "id": "valid", "layers": [{"image": "overlay.png", "method": "contain"}]},
    )
    data = decoration_configuration(
        default=["bad-region", "valid"],
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert set(config.decorations) == {
        "ethereal",
        "hex",
        "lower-flourish",
        "simple-border",
        "top-bottom-borders",
        "valid",
    }
    assert config.default_decorations == ("valid",)
    assert "bad-region/decoration.yaml.presentation_insets" in caplog.text.replace("\\", "/")


def test_unavailable_decoration_preferences_are_ignored_without_rejecting_image(tmp_path: Path, caplog) -> None:
    package = tmp_path / "assets" / "decorations" / "usable"
    package.mkdir(parents=True)
    Image.new("RGBA", (1600, 1200)).save(package / "overlay.png")
    write_asset_manifest(
        package,
        "decoration.yaml",
        {
            "format": 1,
            "id": "usable",
            "layers": [{"image": "overlay.png", "method": "contain"}],
            "font": "missing-font",
            "background": "missing-paper",
            "text_color": [None],
        },
    )
    data = decoration_configuration()

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.decorations["usable"].font is None
    assert config.decorations["usable"].background is None
    assert config.decorations["usable"].text_color is None
    assert "usable" in config.decorations
    assert "missing-font" in caplog.text and "missing-paper" in caplog.text
    assert "decoration.yaml.text_color[0]" in caplog.text


def test_default_decoration_pool_deduplicates_and_falls_back_to_none(tmp_path: Path, caplog) -> None:
    data = decoration_configuration(default=["hex", "none", "hex", "missing", None])
    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_decorations == ("hex", "none")
    assert "decoration identifier 'missing' is unavailable" in caplog.text
    empty = load_application_config(
        write_config(tmp_path / "empty.yaml", decoration_configuration(default=["missing", None]))
    )
    assert empty.default_decorations == ("none",)
    assert "has no usable members; using ['none']" in caplog.text


@pytest.mark.parametrize(
    "identifier", ["none", "ethereal", "hex", "lower-flourish", "simple-border", "top-bottom-borders"]
)
def test_reserved_decoration_identifiers_cannot_be_overridden(tmp_path: Path, identifier: str, caplog) -> None:
    package = tmp_path / "assets" / "decorations" / "conflicting"
    package.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(package / "overlay.png")
    write_asset_manifest(
        package,
        "decoration.yaml",
        {"format": 1, "id": identifier, "layers": [{"image": "overlay.png", "method": "contain"}]},
    )
    config = load_application_config(write_config(tmp_path / "config.yaml", decoration_configuration()))

    if identifier == "none":
        assert identifier not in config.decorations
    else:
        assert config.decorations[identifier].bundled
    assert "reserved" in caplog.text


def test_configuration_background_defaults_support_legacy_direct_construction(tmp_path: Path) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))
    legacy_values = dict(vars(config))
    legacy_values.pop("backgrounds")
    legacy_values.pop("default_backgrounds")

    legacy = type(config)(**legacy_values)

    assert not legacy.backgrounds
    assert legacy.default_backgrounds == ("none",)
    assert replace(legacy).default_backgrounds == ("none",)


def test_loads_defaults_and_bundled_font_resources(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "config.yaml", configuration_data())

    config = load_application_config(config_path)

    assert not hasattr(config, "timezone")
    assert [backend.type for backend in config.display_backends] == ["window"]
    assert config.day_start == time(6)
    assert config.content_directory == tmp_path / "content"
    assert config.reveal.source == time(12)
    assert config.reveal.attribution == time(18)
    assert config.required_output_specifications[0].aspect_ratio == "16:9"
    assert config.required_output_specifications[0].requested_output_size == (1920, 1080)
    assert config.presentation_insets == PresentationInsets(384, 384, 324, 324)
    assert config.default_fonts == ("lora",)
    assert config.min_font_size == 28
    assert config.max_font_size == 100
    assert config.information_view_duration == 60
    assert set(config.fonts) == {"alegreya", "libre-baskerville", "lora", "orbitron", "source-sans-3"}
    assert "orbitron" not in config.default_fonts
    assert all(font.bundled for font in config.fonts.values())
    assert all(font.path.is_file() for font in config.fonts.values())
    assert all(font.path.parent.joinpath("OFL.txt").is_file() for font in config.fonts.values())
    assert config.fonts["orbitron"].path.name == "Orbitron-Regular.ttf"


def test_window_destination_defaults_to_16_9_full_hd(tmp_path: Path) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    output = config.display_backends[0].outputs[0]
    assert output.identifier == "window"
    assert output.output_specification.aspect_ratio == "16:9"
    assert output.output_specification.requested_output_size == (1920, 1080)


def test_window_destination_accepts_explicit_output_specification(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                display={"backends": [{"type": "window", "aspect_ratio": "4:3", "resolution": [1600, 1200]}]}
            ),
        )
    )

    output = config.display_backends[0].outputs[0]
    assert output.output_specification.aspect_ratio == "4:3"
    assert output.output_specification.requested_output_size == (1600, 1200)


@pytest.mark.parametrize(
    "fields",
    [{"aspect_ratio": "4:3"}, {"resolution": [1600, 1200]}],
)
def test_window_output_overrides_must_be_paired(tmp_path: Path, fields: dict[str, object]) -> None:
    data = configuration_data(display={"backends": [{"type": "window", **fields}]})

    fields_present = diagnostic_fields(write_config(tmp_path / "config.yaml", data))
    assert "display.backends[0]" in fields_present


def test_waveshare_destination_is_fixed_to_4_3_1600_by_1200(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(display={"backends": [{"type": "waveshare-13in3-e"}]}),
        )
    )

    specification = config.display_backends[0].outputs[0].output_specification
    assert (specification.aspect_ratio, specification.requested_output_size) == ("4:3", (1600, 1200))


@pytest.mark.parametrize("override", [{"aspect_ratio": "4:3"}, {"resolution": [1600, 1200]}])
def test_waveshare_rejects_output_overrides(tmp_path: Path, override: dict[str, object]) -> None:
    data = configuration_data(display={"backends": [{"type": "waveshare-13in3-e", **override}]})

    assert f"display.backends[0].{next(iter(override))}" in diagnostic_fields(
        write_config(tmp_path / "config.yaml", data)
    )


def test_content_directory_default_is_configuration_relative(tmp_path: Path) -> None:
    data = configuration_data()
    data.pop("content")

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.content_directory == tmp_path / "content"


def test_omitted_content_directory_uses_default_without_information_diagnostic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = configuration_data()
    data["content"] = {}
    config_path = write_config(tmp_path / "config.yaml", data)
    caplog.set_level("INFO")

    config = load_application_config(config_path)

    assert config.content_directory == tmp_path / "content"
    assert not any("content.directory" in record.message for record in caplog.records)


def test_representative_configuration_example_loads() -> None:
    config = load_application_config(Path(__file__).parent.parent / "examples" / "config.yaml")

    assert [backend.type for backend in config.display_backends] == ["window", "image-server"]
    assert config.default_fonts == ("alegreya", "libre-baskerville", "lora", "orbitron", "source-sans-3")
    assert config.default_backgrounds == (
        "none",
        "aged-paper",
        "canvas",
        "cloth",
        "drafting-grid",
        "handmade-paper",
        "hex",
        "isometric-grid",
        "limestone",
        "recursive-squares",
        "vellum",
    )
    assert config.default_decorations == (
        "none",
        "ethereal",
        "hex",
        "lower-flourish",
        "simple-border",
        "top-bottom-borders",
    )
    assert [(spec.aspect_ratio, spec.requested_output_size) for spec in config.required_output_specifications] == [
        ("16:10", (3840, 2400)),
        ("16:9", (1920, 1080))
    ]
    assert config.presentation_insets == PresentationInsets(384, 384, 324, 324)
    assert config.information_view_duration == 5


@pytest.mark.parametrize("duration", [0, 1, 60, 300])
def test_information_view_duration_accepts_inclusive_integer_range(tmp_path: Path, duration: int) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(information_view={"duration": duration}),
        )
    )

    assert config.information_view_duration == duration


@pytest.mark.parametrize("duration", [True, False, "60", 1.5, -1, 301])
def test_invalid_information_view_duration_warns_and_uses_default(tmp_path: Path, duration: object, caplog) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(information_view={"duration": duration}),
        )
    )

    assert config.information_view_duration == 60
    assert "information_view.duration" in caplog.text
    assert "using the documented default 60" in caplog.text


def test_information_view_duration_defaults_when_mapping_or_field_is_omitted(tmp_path: Path) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))
    explicit_empty = load_application_config(
        write_config(
            tmp_path / "explicit-empty.yaml",
            configuration_data(information_view={}),
        )
    )

    assert config.information_view_duration == explicit_empty.information_view_duration == 60


def test_recognizes_reserved_waveshare_backend(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(display={"backends": [{"type": "waveshare-13in3-e"}]}),
        )
    )

    assert config.display_backends[0].type == "waveshare-13in3-e"


def test_image_server_configuration_defaults_and_explicit_settings(tmp_path: Path, caplog) -> None:
    with caplog.at_level("INFO"):
        default_config = load_application_config(
            write_config(
                tmp_path / "default.yaml",
                configuration_data(display={"backends": [{"type": "image-server", "outputs": [{"id": "default"}]}]}),
            )
        )
    configured = load_application_config(
        write_config(
            tmp_path / "configured.yaml",
            configuration_data(
                display={
                    "backends": [
                        {
                            "type": "image-server",
                            "host": "0.0.0.0",
                            "port": 8123,
                            "outputs": [{"id": "default"}],
                        }
                    ],
                }
            ),
        )
    )

    assert "display.backends[0].host" in caplog.text
    assert "display.backends[0].port" in caplog.text
    assert default_config.display_backends[0].host == "127.0.0.1"
    assert default_config.display_backends[0].port == 8080
    default_output = default_config.display_backends[0].outputs[0].output_specification
    assert (default_output.aspect_ratio, default_output.requested_output_size) == ("16:10", (3840, 2400))
    assert configured.display_backends[0].host == "0.0.0.0"
    assert configured.display_backends[0].port == 8123


@pytest.mark.parametrize("outputs", [None, [], "default"])
def test_image_server_requires_nonempty_outputs(tmp_path: Path, outputs: object) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(display={"backends": [{"type": "image-server", "outputs": outputs}]}),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "display.backends[0].outputs" for item in error.value.diagnostics)


@pytest.mark.parametrize("output_id", ["", " ", None, 1])
def test_image_server_output_ids_must_be_nonempty_strings(tmp_path: Path, output_id: object) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            display={"backends": [{"type": "image-server", "outputs": [{"id": output_id}]}]}
        ),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "display.backends[0].outputs[0].id" for item in error.value.diagnostics)


def test_image_server_rejects_duplicate_output_ids(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            display={
                "backends": [
                    {"type": "image-server", "outputs": [{"id": "room"}, {"id": "room"}]}
                ]
            }
        ),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "display.backends[0].outputs[1].id" for item in error.value.diagnostics)


@pytest.mark.parametrize(
    "fields",
    [{"aspect_ratio": "4:3"}, {"resolution": [1600, 1200]}],
)
def test_image_server_output_overrides_must_be_paired(tmp_path: Path, fields: dict[str, object]) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            display={
                "backends": [
                    {"type": "image-server", "outputs": [{"id": "default", **fields}]}
                ]
            }
        ),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(
        item.field == "display.backends[0].outputs[0]"
        for item in error.value.diagnostics
    )


def test_image_server_outputs_resolve_independently_and_share_duplicate_specifications(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                display={
                    "backends": [
                        {"type": "window"},
                        {
                            "type": "image-server",
                            "outputs": [
                                {"id": "default"},
                                {"id": "wide", "aspect_ratio": "16:9", "resolution": [1920, 1080]},
                                {"id": "portrait-ish", "aspect_ratio": "4:3", "resolution": [1600, 1200]},
                            ],
                        },
                    ]
                }
            ),
        )
    )

    assert {
        (specification.aspect_ratio, specification.requested_output_size)
        for specification in config.required_output_specifications
    } == {("16:9", (1920, 1080)), ("16:10", (3840, 2400)), ("4:3", (1600, 1200))}
    assert len(config.required_output_specifications) == 3


@pytest.mark.parametrize(
    ("image_server", "expected_field"),
    [
        ({"unknown": 1}, "display.backends[1].unknown"),
        ({"host": ""}, "display.backends[1].host"),
        ({"host": "not a hostname"}, "display.backends[1].host"),
        ({"host": True}, "display.backends[1].host"),
        ({"port": True}, "display.backends[1].port"),
        ({"port": "8080"}, "display.backends[1].port"),
        ({"port": 0}, "display.backends[1].port"),
        ({"port": 65536}, "display.backends[1].port"),
    ],
)
def test_invalid_image_server_settings_are_recoverable(
    tmp_path: Path, image_server: object, expected_field: str, caplog
) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                display={
                    "backends": [
                        {"type": "window"},
                        {"type": "image-server", "outputs": [{"id": "default"}], **image_server},
                    ]
                }
            ),
        )
    )

    assert expected_field in caplog.text
    assert config.display_backends[1].host == "127.0.0.1"
    assert config.display_backends[1].port == 8080


@pytest.mark.parametrize(
    ("display", "expected_message"),
    [
        (None, "is required"),
        ({}, "is required"),
        ({"backends": "window"}, "nonempty sequence"),
        ({"backends": [{"type": "unknown"}]}, "supported backends"),
        ({"backends": [{"type": "window"}, {"type": "window"}]}, "duplicates backend"),
    ],
)
def test_required_and_invalid_display_backend_are_rejected(
    tmp_path: Path, display: object, expected_message: str
) -> None:
    data = configuration_data()
    if display is None:
        data.pop("display")
    else:
        data["display"] = display
    config_path = write_config(tmp_path / "config.yaml", data)

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    diagnostic = next(item for item in error.value.diagnostics if item.severity >= 40)
    assert expected_message in diagnostic.message


def test_singular_display_configuration_is_not_supported(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "config.yaml", configuration_data(display={"backend": "window"}))

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "display.backends" for item in error.value.diagnostics)


def test_non_mapping_backend_entry_is_diagnosed(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(display={"backends": [{"type": "window"}, None]}),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "display.backends[1]" for item in error.value.diagnostics)


def test_optional_mappings_default_and_absolute_paths_are_preserved(tmp_path: Path) -> None:
    absolute_content = tmp_path / "absolute-content"
    data = configuration_data(content={"directory": str(absolute_content)}, reveal={"source": "08:00"})
    config = load_application_config(write_config(tmp_path / "nested" / "config.yaml", data))

    assert config.content_directory == absolute_content
    assert config.day_start == time(6)
    assert config.reveal.source == time(8)
    assert config.reveal.attribution == time(18)
    assert config.default_fonts == ("lora",)


def test_reveal_times_at_display_day_boundaries_are_valid(tmp_path: Path) -> None:
    data = configuration_data(
        general={"timezone": "UTC", "day_start": "23:59"},
        reveal={"source": "23:59", "attribution": "23:59"},
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.day_start == time(23, 59)
    assert config.reveal.source == time(23, 59)
    assert config.reveal.attribution == time(23, 59)


def test_user_font_is_resolved_and_retained_outside_default_pool(tmp_path: Path) -> None:
    source_font = files("refrain").joinpath("assets", "fonts", "source-sans-3", "SourceSans3-Regular.ttf")
    package = tmp_path / "assets" / "fonts" / "extra"
    user_font = package / "Regular.ttf"
    user_font.parent.mkdir(parents=True)
    with source_font.open("rb") as source, user_font.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    write_asset_manifest(package, "font.yaml", {"format": 1, "id": "extra", "faces": {"regular": "Regular.ttf"}})
    data = configuration_data(
        layout={
            "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 28, "max_font_size": 100},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.fonts["extra"].path == user_font
    assert not config.fonts["extra"].bundled
    assert config.default_fonts == ("lora",)


def test_category_relative_resources_use_the_effective_config_directory_and_nested_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_directory = tmp_path / "alternate" / "configuration"
    font = config_directory / "assets" / "fonts" / "family" / "Regular.ttf"
    background = config_directory / "assets" / "backgrounds" / "backgrounds" / "Paper.png"
    decoration = config_directory / "assets" / "decorations" / "borders" / "Border.png"
    font.parent.mkdir(parents=True)
    background.parent.mkdir(parents=True)
    decoration.parent.mkdir(parents=True)
    font.write_bytes(files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf").read_bytes())
    Image.new("RGB", (1600, 1200)).save(background)
    Image.new("RGBA", (1600, 1200)).save(decoration)
    write_asset_manifest(font.parent, "font.yaml", {"format": 1, "id": "family", "faces": {"regular": "Regular.ttf"}})
    write_asset_manifest(
        decoration.parent,
        "decoration.yaml",
        {"format": 1, "id": "border", "layers": [{"image": "Border.png", "method": "contain"}]},
    )

    data = configuration_data(
        content={"directory": "entries"},
        layout={
            "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
            "fonts": {"default": ["lora"]},
            "backgrounds": {"default": ["none"]},
            "decorations": {"default": ["none"]},
            "text": {"min_font_size": 28, "max_font_size": 100},
        },
    )
    config_path = write_config(config_directory / "config.yaml", data)
    working_directory = tmp_path / "unrelated-working-directory"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    config = load_application_config(config_path)

    assert config.fonts["family"].path == font
    assert config.backgrounds["Paper"].path == background
    assert config.decorations["border"].layers[0].image == decoration
    assert config.content_directory == config_directory / "entries"


@pytest.mark.parametrize("absolute_path", ["/tmp/custom-font.ttf", r"C:\Users\example\custom-font.ttf"])
def test_absolute_font_manifest_path_is_rejected(tmp_path: Path, caplog, absolute_path: str) -> None:
    data = configuration_data(
        layout={
            "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 28, "max_font_size": 100},
        }
    )

    package = tmp_path / "assets" / "fonts" / "extra"
    package.mkdir(parents=True)
    write_asset_manifest(
        package,
        "font.yaml",
        {"format": 1, "id": "extra", "faces": {"regular": absolute_path}},
    )
    config = load_application_config(write_config(tmp_path / "config.yaml", data))
    assert "extra" not in config.fonts
    assert "resource path must be relative" in caplog.text


def test_mixed_discovered_font_bundles_keep_only_usable_fonts(tmp_path: Path, caplog) -> None:
    source_font = files("refrain").joinpath("assets", "fonts", "source-sans-3", "SourceSans3-Regular.ttf")
    valid_package = tmp_path / "assets" / "fonts" / "valid-user-font"
    valid_font = valid_package / "Regular.ttf"
    valid_package.mkdir(parents=True)
    valid_font.write_bytes(source_font.read_bytes())
    write_asset_manifest(
        valid_package, "font.yaml", {"format": 1, "id": "valid-user-font", "faces": {"regular": "Regular.ttf"}}
    )
    missing_package = tmp_path / "assets" / "fonts" / "missing-user-font"
    write_asset_manifest(
        missing_package,
        "font.yaml",
        {"format": 1, "id": "missing-user-font", "faces": {"regular": "missing.ttf"}},
    )
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                layout={
                    "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
                    "fonts": {"default": ["valid-user-font", "missing-user-font"]},
                    "text": {"min_font_size": 28, "max_font_size": 100},
                }
            ),
        )
    )

    assert "valid-user-font" in config.fonts
    assert "missing-user-font" not in config.fonts
    assert config.default_fonts == ("valid-user-font",)
    assert "missing-user-font" in caplog.text
    assert "excluded" in caplog.text


def test_non_string_configuration_keys_are_warned_and_ignored(tmp_path: Path, caplog) -> None:
    config_data = configuration_data(
        general={"timezone": "UTC", 1: "ignored", "unknown": "ignored"},
        layout={
            "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
            "fonts": {"default": ["lora"], "available": {1: "ignored.ttf"}},
            "text": {"min_font_size": 28, "max_font_size": 100},
        },
    )
    config = load_application_config(write_config(tmp_path / "config.yaml", config_data))

    assert config.default_fonts == ("lora",)
    assert 1 not in config.fonts
    assert "general[1]" in caplog.text
    assert "general.timezone" in caplog.text
    assert "layout.fonts.available: is no longer supported" in caplog.text
    assert "ignored" in caplog.text


@pytest.mark.parametrize(
    ("insets", "expected_field"),
    [
        ({}, "layout.presentation_insets.left"),
        ({"left": -1, "right": 384, "top": 324, "bottom": 324}, "layout.presentation_insets.left"),
        ({"left": True, "right": 384, "top": 324, "bottom": 324}, "layout.presentation_insets.left"),
        ({"left": 1.5, "right": 384, "top": 324, "bottom": 324}, "layout.presentation_insets.left"),
        ({"left": 1920, "right": 1920, "top": 324, "bottom": 324}, "layout.presentation_insets"),
        ({"left": 384, "right": 384, "top": 1080, "bottom": 1080}, "layout.presentation_insets"),
    ],
)
def test_invalid_presentation_insets_are_rejected(
    tmp_path: Path, insets: dict[str, int | float | bool], expected_field: str
) -> None:
    data = configuration_data(
        layout={
            "presentation_insets": insets,
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 1, "max_font_size": 2},
        }
    )

    assert expected_field in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_presentation_insets_accept_zero_edges(tmp_path: Path) -> None:
    data = configuration_data(
        layout={
            "presentation_insets": {"left": 0, "right": 0, "top": 0, "bottom": 0},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 1, "max_font_size": 2},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.presentation_insets == PresentationInsets(0, 0, 0, 0)


def test_unsupported_layout_field_is_ignored_with_warning(tmp_path: Path, caplog) -> None:
    data = configuration_data(
        layout={
            "quotation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 1, "max_font_size": 2},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert [(spec.aspect_ratio, spec.requested_output_size) for spec in config.required_output_specifications] == [
        ("16:9", (1920, 1080))
    ]
    assert "layout.quotation_region" in caplog.text
    assert "ignored" in caplog.text


@pytest.mark.parametrize(
    ("data", "expected_field"),
    [
        (
            configuration_data(
                layout={
                    "presentation_insets": {"left": 3840, "right": 0, "top": 0, "bottom": 0},
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 1, "max_font_size": 2},
                }
            ),
            "layout.presentation_insets",
        ),
        (
            configuration_data(
                layout={
                    "presentation_insets": {"left": True, "right": 384, "top": 324, "bottom": 324},
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 1, "max_font_size": 2},
                }
            ),
            "layout.presentation_insets.left",
        ),
        (
            configuration_data(
                layout={
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 10, "max_font_size": 9},
                }
            ),
            "layout.text.max_font_size",
        ),
        (
            configuration_data(
                layout={
                    "fonts": {"default": []},
                    "text": {"min_font_size": 1, "max_font_size": 2},
                }
            ),
            "layout.fonts.default",
        ),
    ],
)
def test_invalid_required_fields_are_fatal(tmp_path: Path, data: dict[str, object], expected_field: str) -> None:
    fields = diagnostic_fields(write_config(tmp_path / "config.yaml", data))

    assert expected_field in fields


def test_missing_optional_defaults_and_invalid_optional_values_are_reported(tmp_path: Path, caplog) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            general={"timezone": "UTC", "day_start": "6:00", "unknown": True},
            reveal={"quotation": "00:00", "source": "invalid"},
            unexpected=True,
        ),
    )

    with caplog.at_level("INFO"):
        config = load_application_config(config_path)

    assert config.day_start == time(6)
    assert config.reveal.source == time(12)
    assert "using documented defaults" in caplog.text
    assert "general.day_start" in caplog.text
    assert "general.timezone" in caplog.text
    assert "reveal.quotation" in caplog.text
    assert "is not a supported configuration field; it is ignored" in caplog.text
    assert "reveal.source" in caplog.text
    assert "general.unknown" in caplog.text
    assert "unexpected" in caplog.text
    assert "using" in caplog.text and "ignored" in caplog.text


@pytest.mark.parametrize(
    ("default_fonts", "expected"),
    [
        (["lora", "lora"], ("lora",)),
        (["lora", "unavailable"], ("lora",)),
        (["unavailable"], ()),
    ],
)
def test_default_font_pool_filters_unavailable_and_duplicates(
    tmp_path: Path, default_fonts: list[str], expected: tuple[str, ...], caplog
) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                layout={
                    "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
                    "fonts": {"default": default_fonts},
                    "text": {"min_font_size": 28, "max_font_size": 100},
                }
            ),
        )
    )

    assert config.default_fonts == expected
    if len(default_fonts) != len(expected):
        assert "ignored" in caplog.text or "excluded" in caplog.text


@pytest.mark.parametrize(
    "contents",
    [
        "general: [not, a, mapping",
        "- one\n- two\n",
        "general: &shared {timezone: UTC}\ncontent: *shared\n",
        "general:\n  timezone: UTC\n  timezone: America/Toronto\n",
        "general:\n  timezone: UTC\n---\ngeneral:\n  timezone: UTC\n",
    ],
)
def test_invalid_yaml_is_rejected(tmp_path: Path, contents: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(contents, encoding="utf-8")

    assert "$" in diagnostic_fields(config_path)


def test_missing_config_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"

    assert "$" in diagnostic_fields(missing)


def test_unreadable_config_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = write_config(tmp_path / "config.yaml", configuration_data())
    original_open = Path.read_text

    def deny_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == config_path:
            raise PermissionError("permission denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_read)

    assert "$" in diagnostic_fields(config_path)


def test_font_collisions_and_invalid_bundles_are_excluded(tmp_path: Path, caplog) -> None:
    font_bytes = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf").read_bytes()
    for package in (
        tmp_path / "assets" / "fonts" / "reserved",
        tmp_path / "assets" / "fonts" / "duplicate-a",
        tmp_path / "assets" / "fonts" / "duplicate-b",
    ):
        package.mkdir(parents=True)
        (package / "Regular.ttf").write_bytes(font_bytes)
    write_asset_manifest(
        tmp_path / "assets" / "fonts" / "reserved",
        "font.yaml",
        {"format": 1, "id": "lora", "faces": {"regular": "Regular.ttf"}},
    )
    for directory in ("duplicate-a", "duplicate-b"):
        write_asset_manifest(
            tmp_path / "assets" / "fonts" / directory,
            "font.yaml",
            {"format": 1, "id": "duplicate", "faces": {"regular": "Regular.ttf"}},
        )
    missing = tmp_path / "assets" / "fonts" / "missing"
    write_asset_manifest(missing, "font.yaml", {"format": 1, "id": "missing", "faces": {"regular": "missing.ttf"}})
    invalid = tmp_path / "assets" / "fonts" / "invalid"
    invalid.mkdir()
    (invalid / "Regular.ttf").write_bytes(b"not a font")
    write_asset_manifest(invalid, "font.yaml", {"format": 1, "id": "invalid", "faces": {"regular": "Regular.ttf"}})

    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    assert config.fonts["lora"].bundled
    assert "duplicate" not in config.fonts
    assert "missing" not in config.fonts
    assert "invalid" not in config.fonts
    assert "conflicts with reserved bundled identifier 'lora'" in caplog.text
    assert "share identifier 'duplicate'; all are excluded" in caplog.text
    assert "resource path is missing" in caplog.text
    assert "unsupported by Pillow" in caplog.text


def test_unreadable_user_font_is_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    package = tmp_path / "assets" / "fonts" / "extra"
    package.mkdir(parents=True)
    user_font = package / "font.ttf"
    user_font.write_bytes(files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf").read_bytes())
    data = configuration_data(
        layout={
            "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 28, "max_font_size": 100},
        }
    )
    write_asset_manifest(package, "font.yaml", {"format": 1, "id": "extra", "faces": {"regular": "font.ttf"}})
    config_path = write_config(tmp_path / "config.yaml", data)
    original_open = Path.open

    def deny_font_read(path: Path, *args: object, **kwargs: object):
        if path == user_font:
            raise PermissionError("permission denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_font_read)

    config = load_application_config(config_path)
    assert "font.yaml.faces.regular" in caplog.text
    assert "extra" not in config.fonts

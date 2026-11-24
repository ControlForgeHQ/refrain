from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import replace
from datetime import date, time
from pathlib import Path
from random import Random
from zipfile import Path as ZipPath
from zipfile import ZipFile

import pytest
import yaml
from PIL import Image
from resource_helpers import write_font_bundle

from refrain import (
    ApplicationConfigurationError,
    BackgroundResource,
    DailySnapshot,
    DecorationLayerResource,
    DecorationResource,
    PresentationInsets,
    SchedulingContext,
    load_application_config,
    load_background_image,
    load_decoration_layer_image,
    prepare_daily_images,
    resolve_reveal_stages,
)
from refrain.geometry import ResolvedOutputSpecification


def configuration_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "destinations": [{"id": "desktop", "type": "window", "audience": "private"}],
        "fonts": {"pools": {"default": ["test-font"]}},
        "text": {
            "colors": {"pools": {"default": ["black"]}},
            "min_font_size": 28,
            "max_font_size": 100,
        },
        "backgrounds": {"pools": {"default": ["none"]}},
        "decorations": {
            "pools": {"default": ["none"]},
            "colors": {"pools": {"default": ["black"]}},
        },
    }
    data.update(overrides)
    if "destinations" in overrides and isinstance(overrides["destinations"], list):
        data["destinations"] = [
            (
                {**destination, "audience": destination.get("audience", "private")}
                if isinstance(destination, dict)
                else destination
            )
            for destination in overrides["destinations"]
        ]
    return data


def write_config(path: Path, data: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_font_bundle(path.parent / "assets" / "fonts" / "test-font")
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
    data["backgrounds"] = {"pools": {key: value for key, value in settings.items() if key != "available"}}
    if "available" in settings:
        data["backgrounds"]["available"] = settings["available"]
    return data


def decoration_configuration(**settings: object) -> dict[str, object]:
    data = configuration_data()
    data["decorations"]["pools"] = settings
    return data


def test_bundled_background_registry_and_plain_default(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    assert config.backgrounds
    assert config.default_backgrounds == ("none",)
    assert all(resource.bundled for resource in config.backgrounds.values())
    assert not any(record.levelno >= 30 and "background" in record.message for record in caplog.records)
    for identifier, resource in config.backgrounds.items():
        assert resource.identifier == identifier
        assert resource.path is None or resource.path.name == f"{identifier}.png"
        assert resource.path is not None or resource.layers
    with pytest.raises(TypeError):
        config.backgrounds["other"] = next(iter(config.backgrounds.values()))


def test_publish_destinations_share_backend_and_use_explicit_geometry(tmp_path: Path) -> None:
    data = configuration_data(
        destinations=[
            {
                "id": "web-public",
                "type": "publish",
                "audience": "public",
                "aspect_ratio": "16:10",
                "resolution": [320, 200],
            },
            {
                "id": "web-private",
                "type": "publish",
                "audience": "private",
                "aspect_ratio": "16:10",
                "resolution": [320, 200],
            },
            {
                "id": "web-custom",
                "type": "publish",
                "audience": "private",
                "aspect_ratio": "16:9",
                "resolution": [320, 180],
                "overrides": {"background": "none"},
            },
        ]
    )

    configuration = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert len(configuration.display_backends) == 1
    backend = configuration.display_backends[0]
    assert backend.type == "publish"
    assert [destination.identifier for destination in backend.outputs] == [
        "web-public",
        "web-private",
        "web-custom",
    ]
    assert [destination.output_specification for destination in backend.outputs] == [
        ResolvedOutputSpecification("16:10", (320, 200)),
        ResolvedOutputSpecification("16:10", (320, 200)),
        ResolvedOutputSpecification("16:9", (320, 180)),
    ]
    assert backend.outputs[0].prepared_image_key == backend.outputs[1].prepared_image_key
    assert backend.outputs[1].prepared_image_key != backend.outputs[2].prepared_image_key


def test_publish_destination_defaults_geometry_when_pair_is_omitted(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(destinations=[{"id": "web-public", "type": "publish", "audience": "public"}]),
    )

    configuration = load_application_config(config_path)
    destination = configuration.display_backends[0].outputs[0]

    assert destination.output_specification.aspect_ratio == "16:10"
    assert destination.output_specification.requested_output_size == (3840, 2400)


@pytest.mark.parametrize(
    "destination",
    [
        {"id": "web", "type": "publish", "audience": "public", "resolution": [320, 200]},
        {"id": "web", "type": "publish", "audience": "public", "aspect_ratio": "16:10"},
    ],
)
def test_publish_destination_rejects_incomplete_geometry_pair(tmp_path: Path, destination: dict[str, object]) -> None:
    config_path = write_config(tmp_path / "config.yaml", configuration_data(destinations=[destination]))
    assert "destinations[0]" in diagnostic_fields(config_path)


def test_publish_destination_directory_ids_are_case_insensitively_unique(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            destinations=[
                {
                    "id": "web-public",
                    "type": "publish",
                    "audience": "public",
                    "aspect_ratio": "16:10",
                    "resolution": [320, 200],
                },
                {
                    "id": "WEB-PUBLIC",
                    "type": "publish",
                    "audience": "private",
                    "aspect_ratio": "16:10",
                    "resolution": [320, 200],
                },
            ]
        ),
    )
    assert "destinations[1].id" in diagnostic_fields(config_path)


@pytest.mark.parametrize("identifier", ["CON", "com1", "Lpt9"])
def test_publish_destination_rejects_windows_reserved_directory_ids(tmp_path: Path, identifier: str) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            destinations=[
                {
                    "id": identifier,
                    "type": "publish",
                    "audience": "public",
                    "aspect_ratio": "16:10",
                    "resolution": [320, 200],
                }
            ]
        ),
    )

    assert "destinations[0].id" in diagnostic_fields(config_path)


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
    data["decorations"]["colors"]["pools"] = {"default": ["sage-green", "missing", "sage-green", "terracotta", None]}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_decoration_colors == ("sage-green", "terracotta")
    assert "palette identifier 'missing' is unavailable" in caplog.text
    assert "duplicates palette identifier 'sage-green'" in caplog.text
    assert "decorations.colors.pools.default[4]" in caplog.text


@pytest.mark.parametrize("pool", [None, [], "bad", ["missing"], ["", None]])
def test_unusable_decoration_color_pool_remains_empty(tmp_path: Path, caplog, pool: object) -> None:
    data = configuration_data()
    data["decorations"]["colors"]["pools"] = {"default": pool}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_decoration_colors == ()
    assert "decorations.colors.pools" in caplog.text


def test_named_pools_expand_recursively_in_order_with_cycle_and_duplicate_handling(tmp_path: Path, caplog) -> None:
    write_font_bundle(tmp_path / "assets" / "fonts" / "second-font", "second-font")
    for identifier in ("surface", "surface-alt"):
        path = tmp_path / "assets" / "backgrounds" / f"{identifier}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 6)).save(path)
    decoration_root = tmp_path / "assets" / "decorations" / "trim"
    decoration_root.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(decoration_root / "layer.png")
    write_asset_manifest(
        decoration_root,
        "decoration.yaml",
        {"format": 1, "id": "trim", "layers": [{"image": "layer.png"}]},
    )
    data = configuration_data()
    write_font_bundle(tmp_path / "assets" / "fonts" / "other-font", "other-font")
    data["palette"] = {"sage": "#8B956A", "navy": "#354B63"}
    data.update(
        {
            "fonts": {
                "pools": {
                    "default": ["@favorites", "@other-favorites"],
                    "favorites": ["test-font", "@shared", "test-font"],
                    "shared": ["second-font", "@favorites"],
                    "other-favorites": ["@shared", "other-font"],
                    "empty": [],
                }
            },
            "backgrounds": {
                "pools": {
                    "default": ["@paper", "none"],
                    "paper": ["surface", "@alternate"],
                    "alternate": ["surface-alt", "@paper"],
                }
            },
            "decorations": {
                "pools": {
                    "default": ["@frames", "none"],
                    "frames": ["trim", "@empty-frames"],
                    "empty-frames": [],
                },
                "colors": {
                    "pools": {
                        "default": ["@accents"],
                        "accents": ["navy", "@shared-colors", "navy"],
                        "shared-colors": ["black", "@accents"],
                    }
                },
            },
            "text": {
                "colors": {
                    "pools": {
                        "default": ["@accents", "sage"],
                        "accents": ["sage", "@shared-colors", "sage"],
                        "shared-colors": ["navy", "@accents"],
                    }
                },
                "min_font_size": 28,
                "max_font_size": 100,
            },
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_fonts == ("test-font", "second-font", "other-font")
    assert config.font_pools["empty"] == ()
    assert config.default_backgrounds == ("surface", "surface-alt", "none")
    assert config.default_decorations == ("trim", "none")
    assert config.default_text_colors == ("sage", "navy")
    assert config.default_decoration_colors == ("navy", "black")
    assert "circular" not in caplog.text.lower()


def test_named_pool_invalid_and_reserved_definitions_are_excluded_independently(tmp_path: Path, caplog) -> None:
    data = configuration_data()
    data["fonts"] = {
        "pools": {
            "default": ["@loop", "@unknown", "@@", "not-installed", "test-font"],
            "loop": ["@other", "test-font"],
            "other": ["@loop", "test-font"],
            "empty": [],
            "malformed": "test-font",
            "bad name": ["test-font"],
            "builtin": ["not-installed"],
        }
    }

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_fonts == ("test-font",)
    assert config.font_pools["empty"] == ()
    assert config.font_pools["malformed"] == ()
    assert "fonts.pools.default[1]" in caplog.text
    assert "pool reference '@@' is malformed" in caplog.text
    assert "fonts.pools.not-installed" not in caplog.text
    assert "fonts.pools.builtin" in caplog.text
    assert "fonts.pools.bad name" in caplog.text
    assert "circular" not in caplog.text.lower()


def test_empty_named_default_pools_preserve_expanded_membership(tmp_path: Path) -> None:
    data = configuration_data()
    data.update(
        {
            "fonts": {"pools": {"default": ["@empty"], "empty": [], "nested": ["@default"]}},
            "backgrounds": {"pools": {"default": ["@empty"], "empty": [], "nested": ["@default"]}},
            "decorations": {
                "pools": {
                    "default": ["@empty"],
                    "empty": [],
                    "nested": ["@default"],
                },
                "colors": {"pools": {"default": ["@empty"], "empty": [], "nested": ["@default"]}},
            },
            "text": {
                "colors": {"pools": {"default": ["@empty"], "empty": [], "nested": ["@default"]}},
                "min_font_size": 28,
                "max_font_size": 100,
            },
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    for pools, default in (
        (config.font_pools, config.default_fonts),
        (config.background_pools, config.default_backgrounds),
        (config.decoration_pools, config.default_decorations),
        (config.text_color_pools, config.default_text_colors),
        (config.decoration_color_pools, config.default_decoration_colors),
    ):
        assert default == pools["default"] == pools["empty"] == pools["nested"] == ()


@pytest.mark.parametrize("default", [None, [], "bad", ["missing"]])
def test_invalid_optional_default_declarations_do_not_gain_fallback_members(tmp_path: Path, default: object) -> None:
    data = configuration_data(
        backgrounds={"pools": {"default": deepcopy(default)}},
        decorations={"pools": {"default": deepcopy(default)}, "colors": {"pools": {"default": deepcopy(default)}}},
        text={"colors": {"pools": {"default": deepcopy(default)}}},
    )
    config = load_application_config(write_config(tmp_path / "config.yaml", data))
    for pools in (
        config.background_pools,
        config.decoration_pools,
        config.text_color_pools,
        config.decoration_color_pools,
    ):
        assert pools["default"] == ()


@pytest.mark.parametrize("fonts", [{}, {"pools": {}}, {"pools": {"default": None}}, {"pools": {"default": []}}])
def test_required_font_default_declaration_cannot_be_missing_or_malformed(tmp_path: Path, fonts: object) -> None:
    assert "fonts.pools.default" in diagnostic_fields(
        write_config(tmp_path / "config.yaml", configuration_data(fonts=fonts))
    )


def test_builtin_pools_follow_successful_bundled_registration_and_exclude_custom_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import refrain.config as config_module

    bundled_root = tmp_path / "package"
    write_font_bundle(bundled_root / "assets" / "fonts" / "bundled-font", "bundled-font")
    backgrounds = bundled_root / "assets" / "backgrounds"
    backgrounds.mkdir(parents=True)
    Image.new("RGB", (8, 6)).save(backgrounds / "bundled-paper.png")
    broken = backgrounds / "broken"
    broken.mkdir()
    write_asset_manifest(
        broken,
        "background.yaml",
        {"format": 1, "id": "unusable-bundled", "layers": [{"image": "missing.png"}]},
    )
    decorations = bundled_root / "assets" / "decorations" / "bundled-frame"
    decorations.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(decorations / "layer.png")
    write_asset_manifest(
        decorations,
        "decoration.yaml",
        {"format": 1, "id": "bundled-frame", "layers": [{"image": "layer.png"}]},
    )
    monkeypatch.setattr(config_module, "files", lambda _package: bundled_root)
    (tmp_path / "assets" / "backgrounds").mkdir(parents=True)
    Image.new("RGB", (8, 6)).save(tmp_path / "assets" / "backgrounds" / "custom-paper.png")
    data = configuration_data()
    data["palette"] = {"black": "#123456"}
    data.update(
        {
            "fonts": {"pools": {"default": ["@builtin"]}},
            "backgrounds": {"pools": {"default": ["@builtin", "none"]}},
            "decorations": {
                "pools": {"default": ["@builtin", "none"]},
                "colors": {"pools": {"default": ["@builtin"]}},
            },
            "text": {
                "colors": {"pools": {"default": ["@builtin"]}},
                "min_font_size": 28,
                "max_font_size": 100,
            },
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_fonts == ("bundled-font",)
    assert config.default_backgrounds == ("bundled-paper", "none")
    assert config.default_decorations == ("bundled-frame", "none")
    assert config.default_text_colors == config.default_decoration_colors == ("black",)
    assert config.palette["black"] == "#123456"
    assert config.background_pools["builtin"] == ("bundled-paper",)
    assert config.decoration_pools["builtin"] == ("bundled-frame",)
    assert "custom-paper" not in config.background_pools["builtin"]
    assert "unusable-bundled" not in config.backgrounds
    assert "unusable-bundled" not in config.background_pools["builtin"]

    write_font_bundle(bundled_root / "assets" / "fonts" / "added-font", "added-font")
    Image.new("RGB", (8, 6)).save(backgrounds / "added-paper.png")
    added_decoration = bundled_root / "assets" / "decorations" / "added-frame"
    added_decoration.mkdir()
    Image.new("RGBA", (8, 6)).save(added_decoration / "layer.png")
    write_asset_manifest(
        added_decoration,
        "decoration.yaml",
        {"format": 1, "id": "added-frame", "layers": [{"image": "layer.png"}]},
    )
    reloaded = load_application_config(tmp_path / "config.yaml")
    assert reloaded.default_fonts == ("added-font", "bundled-font")
    assert reloaded.default_backgrounds == ("added-paper", "bundled-paper", "none")
    assert reloaded.default_decorations == ("added-frame", "bundled-frame", "none")

    import shutil

    shutil.rmtree(bundled_root / "assets" / "fonts" / "bundled-font")
    (backgrounds / "bundled-paper.png").unlink()
    shutil.rmtree(decorations)
    reloaded = load_application_config(tmp_path / "config.yaml")
    assert reloaded.default_fonts == ("added-font",)
    assert reloaded.default_backgrounds == ("added-paper", "none")
    assert reloaded.default_decorations == ("added-frame", "none")


def test_decoration_manifest_pool_preferences_are_retained_for_configuration_resolution(tmp_path: Path) -> None:
    background = tmp_path / "assets" / "backgrounds" / "surface.png"
    background.parent.mkdir(parents=True)
    Image.new("RGB", (8, 6)).save(background)
    decoration_root = tmp_path / "assets" / "decorations" / "frame"
    decoration_root.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(decoration_root / "layer.png")
    write_asset_manifest(
        decoration_root,
        "decoration.yaml",
        {
            "format": 1,
            "id": "frame",
            "layers": [{"image": "layer.png"}],
            "font": "@preferred-fonts",
            "background": "@preferred-backgrounds",
            "text_color": "@text-palette",
            "decoration_color": ["@tint-palette"],
        },
    )
    data = configuration_data()
    data["palette"] = {"sage": "#8B956A"}
    data.update(
        {
            "fonts": {"pools": {"default": ["test-font"], "preferred-fonts": ["test-font"]}},
            "backgrounds": {"pools": {"default": ["none"], "preferred-backgrounds": ["surface"]}},
            "decorations": {
                "pools": {"default": ["frame"]},
                "colors": {"pools": {"tint-palette": ["sage"]}},
            },
            "text": {
                "colors": {"pools": {"text-palette": ["sage"]}},
                "min_font_size": 28,
                "max_font_size": 100,
            },
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))
    resource = config.decorations["frame"]

    assert resource.font == "@preferred-fonts"
    assert resource.background == "@preferred-backgrounds"
    assert resource.text_color == ("@text-palette",)
    assert resource.decoration_color == ("@tint-palette",)


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
    data["text"]["colors"]["pools"] = {"default": ["burnt-orange", "missing", "burnt-orange", None, "blue"]}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_text_colors == ("burnt-orange", "blue")
    assert "palette identifier 'missing' is unavailable" in caplog.text
    assert "duplicates palette identifier 'burnt-orange'" in caplog.text


@pytest.mark.parametrize("pool", [None, [], "bad", ["missing"], ["", None]])
def test_unusable_text_color_pool_remains_empty(tmp_path: Path, caplog, pool: object) -> None:
    data = configuration_data()
    data["text"]["colors"]["pools"] = {"default": pool}

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_text_colors == ()
    assert "text.colors.pools" in caplog.text


def test_global_role_face_preferences(tmp_path: Path) -> None:
    data = configuration_data()
    data["fonts"]["faces"] = {"quotation": "regular", "source": "italic"}
    config = load_application_config(write_config(tmp_path / "config.yaml", data))
    assert dict(config.font_faces) == {"quotation": "regular", "source": "italic"}


@pytest.mark.parametrize(
    "preferences",
    [None, [], "bad", {"byline": "italic"}, {"source": None}, {"quotation": ""}, {"attribution": "bad face"}],
)
def test_invalid_global_role_face_preferences_are_warned_and_ignored(
    tmp_path: Path, preferences: object, caplog
) -> None:
    data = configuration_data()
    data["fonts"]["faces"] = preferences

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.font_faces == {}
    assert "fonts.faces" in caplog.text


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


def test_bundled_background_identifier_cannot_be_overridden(tmp_path: Path, caplog) -> None:
    config_path = write_config(tmp_path / "config.yaml", background_configuration())
    identifier = next(iter(load_application_config(config_path).backgrounds))
    asset_path = tmp_path / "assets" / "backgrounds" / f"{identifier}.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6)).save(asset_path)

    config = load_application_config(config_path)

    assert config.backgrounds[identifier].bundled
    assert f"conflicts with bundled identifier {identifier!r}" in caplog.text
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
    baseline = load_application_config(write_config(tmp_path / "baseline.yaml", configuration_data()))
    data = background_configuration(available=available)

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert set(config.backgrounds) == set(baseline.backgrounds)
    assert all(resource.bundled for resource in config.backgrounds.values())
    assert "backgrounds.available" in caplog.text


def test_default_background_pool_deduplicates_and_excludes_invalid_values(tmp_path: Path, caplog) -> None:
    for identifier in ("pool-a", "pool-b"):
        path = tmp_path / "assets" / "backgrounds" / f"{identifier}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 6)).save(path)
    data = background_configuration(
        default=["pool-a", "none", "pool-a", None, False, "", " ", "Pool-a", "pool-b", "none"]
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_backgrounds == ("pool-a", "none", "pool-b")
    assert "background identifier 'Pool-a' is unavailable" in caplog.text
    assert "must be a valid background identifier" in caplog.text


@pytest.mark.parametrize("pool", [None, [], {}, "pool-a", False, ["missing"], ["", None, " "]])
def test_unusable_background_pool_remains_empty(tmp_path: Path, pool: object, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", background_configuration(default=pool)))

    assert config.default_backgrounds == ()
    assert "backgrounds.pools.default" in caplog.text


@pytest.mark.parametrize("section", [None, [], "bad"])
def test_malformed_background_section_warns_and_uses_default(tmp_path: Path, section: object, caplog) -> None:
    data = configuration_data()
    data["backgrounds"] = section

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_backgrounds == ("none",)
    assert "backgrounds: must be a mapping" in caplog.text


def test_unknown_background_settings_warn(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", background_configuration(unknown=True)))

    assert config.default_backgrounds == ("none",)
    assert "backgrounds.pools.unknown" in caplog.text


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
    assert config.default_backgrounds == ()
    assert "assets.background.paper" in caplog.text
    assert "background read denied" in caplog.text
    assert any(resource.bundled for resource in config.backgrounds.values())
    assert any(
        record.levelno == logging.WARNING
        and "assets.background.paper" in record.getMessage()
        and "excluded" in record.getMessage()
        for record in caplog.records
    )


def test_bundled_decoration_registry_and_plain_default(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    assert config.decorations
    assert config.default_decorations == ("none",)
    assert "none" not in config.decorations
    assert all(resource.bundled for resource in config.decorations.values())
    assert not any(record.levelno >= 30 and "decoration" in record.message for record in caplog.records)
    for identifier, resource in config.decorations.items():
        assert resource.identifier == identifier
        assert resource.layers
        for layer in resource.layers:
            with load_decoration_layer_image(layer) as image:
                assert image.width > 0 and image.height > 0
                assert image.mode in {"RGB", "RGBA"}
    with pytest.raises(TypeError):
        config.decorations["other"] = next(iter(config.decorations.values()))


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
            "font": "test-font",
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
        "test-font",
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

    assert "valid" in config.decorations
    assert "bad-region" not in config.decorations
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
    package = tmp_path / "assets" / "decorations" / "pool-frame"
    package.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(package / "overlay.png")
    write_asset_manifest(
        package,
        "decoration.yaml",
        {"format": 1, "id": "pool-frame", "layers": [{"image": "overlay.png", "method": "contain"}]},
    )
    data = decoration_configuration(default=["pool-frame", "none", "pool-frame", "missing", None])
    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_decorations == ("pool-frame", "none")
    assert "decoration identifier 'missing' is unavailable" in caplog.text
    empty = load_application_config(
        write_config(tmp_path / "empty.yaml", decoration_configuration(default=["missing", None]))
    )
    assert empty.default_decorations == ()


def test_bundled_decoration_identifier_cannot_be_overridden(tmp_path: Path, caplog) -> None:
    config_path = write_config(tmp_path / "config.yaml", decoration_configuration())
    identifier = next(iter(load_application_config(config_path).decorations))
    package = tmp_path / "assets" / "decorations" / "conflicting"
    package.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(package / "overlay.png")
    write_asset_manifest(
        package,
        "decoration.yaml",
        {"format": 1, "id": identifier, "layers": [{"image": "overlay.png", "method": "contain"}]},
    )
    config = load_application_config(config_path)

    assert config.decorations[identifier].bundled
    assert f"conflicts with bundled identifier {identifier!r}" in caplog.text


def test_configuration_background_defaults_support_legacy_direct_construction(tmp_path: Path) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))
    legacy_values = dict(vars(config))
    legacy_values.pop("backgrounds")
    legacy_values.pop("default_backgrounds")

    legacy = type(config)(**legacy_values)

    assert not legacy.backgrounds
    assert legacy.default_backgrounds == ("none",)
    assert replace(legacy).default_backgrounds == ("none",)


def test_loads_documented_defaults_with_explicit_required_settings(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "config.yaml", configuration_data())

    config = load_application_config(config_path)

    assert not hasattr(config, "timezone")
    assert [backend.type for backend in config.display_backends] == ["window"]
    assert config.day_start == time(5)
    assert config.content_directory == tmp_path / "content"
    assert config.reveal.source == time(12)
    assert config.reveal.attribution == time(18)
    assert config.required_output_specifications[0].aspect_ratio == "16:9"
    assert config.required_output_specifications[0].requested_output_size == (1920, 1080)
    assert config.presentation_insets == PresentationInsets(384, 384, 324, 324)
    assert config.default_fonts == ("test-font",)
    assert config.min_font_size == 28
    assert config.max_font_size == 100
    assert config.information_view_duration == 60
    assert config.font_faces == {}
    assert config.qr_enabled is True
    assert config.default_backgrounds == config.default_decorations == ("none",)
    assert config.default_text_colors == config.default_decoration_colors == ("black",)


def test_optional_font_size_bounds_default_independently(tmp_path: Path) -> None:
    both_omitted = load_application_config(write_config(tmp_path / "default.yaml", configuration_data(text={})))
    minimum_only = load_application_config(
        write_config(tmp_path / "minimum.yaml", configuration_data(text={"min_font_size": 60}))
    )
    maximum_only = load_application_config(
        write_config(tmp_path / "maximum.yaml", configuration_data(text={"max_font_size": 80}))
    )

    assert (both_omitted.min_font_size, both_omitted.max_font_size) == (56, 200)
    assert (minimum_only.min_font_size, minimum_only.max_font_size) == (60, 200)
    assert (maximum_only.min_font_size, maximum_only.max_font_size) == (56, 80)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "56"])
def test_invalid_explicit_font_size_bounds_remain_errors(tmp_path: Path, value: object) -> None:
    fields = diagnostic_fields(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(text={"min_font_size": value}),
        )
    )

    assert "text.min_font_size" in fields


def test_complete_revised_schema_and_independent_pool_namespaces(tmp_path: Path) -> None:
    data = configuration_data(
        destinations=[
            {"id": "test-font", "type": "window", "aspect_ratio": "16:9", "resolution": [1920, 1080]},
            {"id": "service", "type": "image-server"},
        ],
        **{
            "image-server": None,
            "storage": {
                "content": "entries",
                "state": "state",
                "artifacts": "cache/artifacts",
            },
            "scheduling": {
                "day_start": "05:00",
                "reveal": {"source": "12:00", "attribution": "18:00"},
            },
            "presentation": {
                "insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
                "information_view": {"duration": 30},
                "qr": {"enabled": False},
            },
            "palette": {"black": "#101010", "sage": "#8A9B79"},
            "fonts": {
                "pools": {
                    "default": ["@faces"],
                    "faces": ["test-font"],
                    "complete": ["@builtin"],
                },
                "faces": {"source": "italic"},
            },
            "text": {
                "min_font_size": 56,
                "max_font_size": 200,
                "colors": {"pools": {"default": ["@colors"], "colors": ["sage"]}},
            },
            "backgrounds": {
                "pools": {"default": ["@pools"], "pools": ["none"], "complete": ["@builtin"]},
            },
            "decorations": {
                "pools": {"default": ["@colors"], "colors": ["none"]},
                "colors": {"pools": {"default": ["@pools"], "pools": ["sage"]}},
            },
        },
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_fonts == ("test-font",)
    assert config.font_pools["faces"] == ("test-font",)
    assert config.default_backgrounds == ("none",)
    assert config.background_pools["pools"] == ("none",)
    assert config.default_decorations == ("none",)
    assert config.decoration_pools["colors"] == ("none",)
    assert config.default_text_colors == config.default_decoration_colors == ("sage",)
    assert config.font_faces == {"source": "italic"}
    assert config.palette["black"] == "#101010"
    assert config.content_directory == tmp_path / "entries"
    assert config.storage.state == tmp_path / "state"
    assert config.information_view_duration == 30
    assert config.qr_enabled is False
    assert config.display_backends[1].service_enabled is True


def test_color_pool_list_shorthand_is_unsupported(tmp_path: Path, caplog) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(text={"colors": ["red"]}, decorations={"colors": ["blue"]}),
        )
    )

    assert config.default_text_colors == config.default_decoration_colors == ("black",)
    assert "text.colors: must be a mapping" in caplog.text
    assert "decorations.colors: must be a mapping" in caplog.text


def test_window_destination_defaults_to_16_9_full_hd(tmp_path: Path) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    output = config.display_backends[0].outputs[0]
    assert output.identifier == "desktop"
    assert output.output_specification.aspect_ratio == "16:9"
    assert output.output_specification.requested_output_size == (1920, 1080)
    assert output.audience == "private"


@pytest.mark.parametrize(
    ("backend_type", "audience"),
    [
        ("window", "public"),
        ("window", "private"),
        ("waveshare-13in3-e", "public"),
        ("waveshare-13in3-e", "private"),
        ("image-server", "public"),
        ("image-server", "private"),
    ],
)
def test_each_destination_type_preserves_explicit_audience(tmp_path: Path, backend_type: str, audience: str) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(destinations=[{"id": "destination", "type": backend_type, "audience": audience}]),
        )
    )

    assert config.display_backends[0].outputs[0].audience == audience


@pytest.mark.parametrize("audience", [None, "", "internal", 1, True, [], {}])
def test_invalid_destination_audience_is_a_configuration_error(tmp_path: Path, audience: object) -> None:
    data = configuration_data(destinations=[{"id": "desktop", "type": "window", "audience": audience}])

    assert "destinations[0].audience" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_missing_destination_audience_is_a_configuration_error(tmp_path: Path) -> None:
    data = configuration_data()
    data["destinations"] = [{"id": "desktop", "type": "window"}]

    assert "destinations[0].audience" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_destination_overrides_accept_registered_font_and_builtin_and_custom_colors(tmp_path: Path) -> None:
    write_font_bundle(tmp_path / "assets" / "fonts" / "registered-outside-pool", "registered-outside-pool")
    data = configuration_data(
        destinations=[
            {
                "id": "desktop",
                "type": "window",
                "overrides": {
                    "background": "none",
                    "decoration": "none",
                    "font": "registered-outside-pool",
                    "text_color": "custom-ink",
                    "decoration_color": "black",
                    "qr": "none",
                },
            }
        ],
        palette={"custom-ink": "#123456"},
    )

    configuration = load_application_config(write_config(tmp_path / "config.yaml", data))
    output = configuration.display_backends[0].outputs[0]

    assert "registered-outside-pool" in configuration.fonts
    assert "registered-outside-pool" not in configuration.default_fonts
    assert output.presentation.background == "none"
    assert output.presentation.decoration == "none"
    assert output.presentation.font == "registered-outside-pool"
    assert output.presentation.text_color == ("custom-ink",)
    assert output.presentation.decoration_color == ("black",)
    assert output.presentation.qr_enabled is False


@pytest.mark.parametrize("overrides", [None, []])
def test_destination_overrides_must_be_a_mapping(tmp_path: Path, overrides: object) -> None:
    data = configuration_data(destinations=[{"id": "desktop", "type": "window", "overrides": overrides}])
    assert "destinations[0].overrides" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("background", None),
        ("background", True),
        ("background", "@paper"),
        ("background", "paper"),
        ("decoration", []),
        ("decoration", "@frame"),
        ("decoration", "frame"),
        ("font", None),
        ("font", True),
        ("font", "@default"),
        ("font", ["test-font"]),
        ("text_color", None),
        ("text_color", ["black"]),
        ("text_color", "@colors"),
        ("text_color", "#123456"),
        ("decoration_color", 1),
        ("decoration_color", ["black", "white"]),
        ("decoration_color", "@colors"),
        ("decoration_color", "#123456"),
        ("qr", None),
        ("qr", True),
        ("qr", {"enabled": False}),
    ],
)
def test_destination_overrides_reject_unsupported_types_and_forms(tmp_path: Path, name: str, value: object) -> None:
    data = configuration_data(destinations=[{"id": "desktop", "type": "window", "overrides": {name: value}}])
    assert f"destinations[0].overrides.{name}" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_destination_overrides_reject_unknown_fields(tmp_path: Path) -> None:
    data = configuration_data(destinations=[{"id": "desktop", "type": "window", "overrides": {"contrast": "high"}}])
    assert "destinations[0].overrides.contrast" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


@pytest.mark.parametrize(
    ("name", "value"),
    [("font", "unavailable-font"), ("text_color", "unavailable-color"), ("decoration_color", "unavailable-color")],
)
def test_destination_overrides_require_registered_fonts_and_effective_palette_ids(
    tmp_path: Path, name: str, value: str
) -> None:
    data = configuration_data(destinations=[{"id": "desktop", "type": "window", "overrides": {name: value}}])
    assert f"destinations[0].overrides.{name}" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_omitted_and_empty_destination_overrides_preserve_ungrouped_variants(tmp_path: Path) -> None:
    configuration = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[
                    {"id": "without-overrides", "type": "publish"},
                    {"id": "empty-overrides", "type": "publish", "overrides": {}},
                ]
            ),
        )
    )

    omitted, empty = configuration.display_backends[0].outputs
    assert omitted.presentation.is_empty
    assert empty.presentation.is_empty
    assert omitted.prepared_image_key == empty.prepared_image_key
    assert configuration.required_prepared_image_keys == configuration.required_output_specifications


def test_identical_and_different_destination_overrides_form_compatible_groups(tmp_path: Path) -> None:
    data = configuration_data(
        destinations=[
            {
                "id": "first",
                "type": "publish",
                "overrides": {"background": "none", "text_color": "black"},
            },
            {
                "id": "second",
                "type": "publish",
                "overrides": {"background": "none", "text_color": "black"},
            },
            {
                "id": "third",
                "type": "publish",
                "overrides": {"background": "none", "decoration": "none"},
            },
        ]
    )
    configuration = load_application_config(write_config(tmp_path / "config.yaml", data))
    first, second, third = configuration.display_backends[0].outputs

    assert first.prepared_image_key == second.prepared_image_key
    assert first.prepared_image_key != third.prepared_image_key
    assert len(configuration.required_prepared_image_keys) == 2


def test_valid_destination_overrides_reach_image_preparation(tmp_path: Path) -> None:
    write_font_bundle(tmp_path / "assets" / "fonts" / "registered-outside-pool", "registered-outside-pool")
    data = configuration_data(
        destinations=[
            {
                "id": "desktop",
                "type": "window",
                "overrides": {
                    "background": "none",
                    "decoration": "none",
                    "font": "registered-outside-pool",
                    "text_color": "custom-ink",
                    "decoration_color": "black",
                    "qr": "none",
                },
            }
        ],
        palette={"custom-ink": "#123456"},
    )
    configuration = load_application_config(write_config(tmp_path / "config.yaml", data))
    snapshot = DailySnapshot(
        entry_id="test-entry",
        quotation_text="A quiet moment.",
        quotation_identity="A quiet moment.",
        source=None,
        attribution=None,
        presentation_style="centered",
        font=None,
        font_faces={},
        background="unavailable-background",
        decoration="unavailable-decoration",
        text_color=None,
        decoration_color=None,
        reveal_schedule={
            "quotation": configuration.day_start.strftime("%H:%M"),
            "source": configuration.reveal.source.strftime("%H:%M"),
            "attribution": configuration.reveal.attribution.strftime("%H:%M"),
        },
        scheduling=SchedulingContext(date(2026, 10, 26), configuration.day_start.strftime("%H:%M")),
    )
    metadata = {}
    variants = prepare_daily_images(
        snapshot,
        resolve_reveal_stages(snapshot),
        configuration,
        configuration.required_prepared_image_keys,
        chooser=Random(0),
        selection_revision=1,
        on_metadata=metadata.__setitem__,
    )

    try:
        key = configuration.display_backends[0].outputs[0].prepared_image_key
        reconstruction = metadata[key][0]["reconstruction"]
        assert reconstruction["background"] == "none"
        assert reconstruction["decoration"] == "none"
        assert reconstruction["fonts"]["bundle"] == "registered-outside-pool"
        assert reconstruction["colors"]["text"] == "custom-ink"
        assert reconstruction["qr"]["enabled"] is False
    finally:
        for images in variants.values():
            for image in images:
                image.close()


def test_legacy_destination_presentation_is_ignored_not_interpreted(tmp_path: Path, caplog) -> None:
    configuration = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[
                    {
                        "id": "desktop",
                        "type": "window",
                        "presentation": {"background": "none", "qr": {"enabled": False}},
                    }
                ],
            ),
        )
    )

    assert configuration.display_backends[0].outputs[0].presentation.is_empty
    assert "destinations[0].presentation" in caplog.text


@pytest.mark.parametrize("size", [(1, 1), (600, 800), (800, 800), (3840, 2400), (3840, 1), (1, 2400)])
def test_config_accepts_independent_output_dimensions(tmp_path: Path, size: tuple[int, int]) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[{"id": "desktop", "type": "window", "aspect_ratio": "4:3", "resolution": list(size)}]
            ),
        )
    )
    assert config.display_backends[0].outputs[0].output_specification.requested_output_size == size


@pytest.mark.parametrize("size", [[3841, 1], [1, 2401], [0, 1], [1, True]])
def test_config_rejects_invalid_output_dimensions(tmp_path: Path, size: list[object]) -> None:
    path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            destinations=[{"id": "desktop", "type": "window", "aspect_ratio": "4:3", "resolution": size}]
        ),
    )
    assert "destinations[0].resolution" in diagnostic_fields(path)


def test_window_destination_accepts_explicit_output_specification(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[{"id": "desktop", "type": "window", "aspect_ratio": "4:3", "resolution": [1600, 1200]}]
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
    data = configuration_data(destinations=[{"id": "desktop", "type": "window", **fields}])

    fields_present = diagnostic_fields(write_config(tmp_path / "config.yaml", data))
    assert "destinations[0]" in fields_present


def test_waveshare_destination_is_fixed_to_4_3_1600_by_1200(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(destinations=[{"id": "epaper", "type": "waveshare-13in3-e"}]),
        )
    )

    specification = config.display_backends[0].outputs[0].output_specification
    assert (specification.aspect_ratio, specification.requested_output_size) == ("4:3", (1600, 1200))


@pytest.mark.parametrize("override", [{"aspect_ratio": "4:3"}, {"resolution": [1600, 1200]}])
def test_waveshare_rejects_output_overrides(tmp_path: Path, override: dict[str, object]) -> None:
    data = configuration_data(destinations=[{"id": "epaper", "type": "waveshare-13in3-e", **override}])

    assert f"destinations[0].{next(iter(override))}" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_content_directory_default_is_configuration_relative(tmp_path: Path) -> None:
    data = configuration_data()
    data.pop("storage", None)

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.content_directory == tmp_path / "content"


def test_omitted_content_directory_uses_default_without_information_diagnostic(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = configuration_data()
    data["storage"] = {}
    config_path = write_config(tmp_path / "config.yaml", data)
    caplog.set_level("INFO")

    config = load_application_config(config_path)

    assert config.content_directory == tmp_path / "content"
    assert not any("storage.content" in record.message for record in caplog.records)


def test_storage_content_path_resolves_relative_to_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "alternate" / "config.yaml"

    config = load_application_config(write_config(config_path, configuration_data(storage={"content": "entries"})))

    assert config.content_directory == config_path.parent / "entries"


@pytest.mark.parametrize("storage", [None, {}])
def test_storage_paths_are_optional(tmp_path: Path, storage: object) -> None:
    data = configuration_data()
    if storage is None:
        data.pop("storage", None)
    else:
        data["storage"] = storage

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.storage.state is None
    assert config.storage.artifacts is None
    assert config.storage.publish is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "runtime/state"),
        ("artifacts", "runtime/artifacts"),
        ("publish", "runtime/publish"),
    ],
)
def test_each_configured_storage_path_resolves_relative_to_config_file(tmp_path: Path, field: str, value: str) -> None:
    config_path = tmp_path / "alternate" / "config.yaml"
    config = load_application_config(write_config(config_path, configuration_data(storage={field: value})))

    assert getattr(config.storage, field) == config_path.parent / value
    assert all(getattr(config.storage, other) is None for other in {"state", "artifacts", "publish"} - {field})


def test_storage_paths_accept_absolute_values_and_all_fields_together(tmp_path: Path) -> None:
    configured = {
        "content": tmp_path / "content",
        "state": tmp_path / "state",
        "artifacts": tmp_path / "artifacts",
        "publish": tmp_path / "publish",
    }

    config = load_application_config(
        write_config(
            tmp_path / "nested" / "config.yaml",
            configuration_data(storage={field: str(path) for field, path in configured.items()}),
        )
    )

    assert config.content_directory == configured["content"]
    assert config.storage.state == configured["state"]
    assert config.storage.artifacts == configured["artifacts"]


@pytest.mark.parametrize("field", ["state", "artifacts", "publish"])
@pytest.mark.parametrize("value", [None, 1, True, "", []])
def test_invalid_storage_path_values_are_errors(tmp_path: Path, field: str, value: object) -> None:
    data = configuration_data(storage={field: value})

    assert f"storage.{field}" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


@pytest.mark.parametrize("storage", [None, [], "runtime"])
def test_storage_must_be_a_mapping(tmp_path: Path, storage: object) -> None:
    data = configuration_data(storage=storage)

    assert "storage" in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_unknown_storage_fields_follow_configuration_warning_policy(tmp_path: Path, caplog) -> None:
    config = load_application_config(
        write_config(tmp_path / "config.yaml", configuration_data(storage={"state": "state.json", "other": "ignored"}))
    )

    assert config.storage.state == tmp_path / "state.json"
    assert "storage.other" in caplog.text
    assert "is not a supported configuration field; it is ignored" in caplog.text


def test_history_override_is_ignored_as_an_unknown_field(tmp_path: Path, caplog) -> None:
    config = load_application_config(
        write_config(tmp_path / "config.yaml", configuration_data(storage={"history": "elsewhere.jsonl"}))
    )

    assert not hasattr(config.storage, "history")
    assert "storage.history" in caplog.text


@pytest.mark.parametrize(
    "config_path",
    [
        Path(__file__).parent.parent / "src" / "refrain" / "config.default.yaml",
    ],
    ids=["installed-default"],
)
def test_shipped_configurations_have_usable_pools_and_prepare_images(config_path: Path, tmp_path: Path, caplog) -> None:
    installed = tmp_path / config_path.name
    installed.write_bytes(config_path.read_bytes())
    config = load_application_config(installed)

    assert config.display_backends
    assert config.default_fonts
    assert set(config.default_fonts) <= config.fonts.keys()
    assert set(config.default_backgrounds) <= config.backgrounds.keys() | {"none"}
    assert set(config.default_decorations) <= config.decorations.keys() | {"none"}
    assert set(config.default_text_colors) <= config.palette.keys()
    assert set(config.default_decoration_colors) <= config.palette.keys()
    assert config.day_start <= min(config.reveal.source, config.reveal.attribution)
    assert 0 <= config.information_view_duration <= 300
    assert config.min_font_size == 56
    assert config.max_font_size == 200
    assert config.presentation_insets == PresentationInsets(384, 384, 324, 324)
    assert config.qr_enabled is True
    assert config.storage.state is config.storage.artifacts is None
    assert config.storage.publish is None

    snapshot = DailySnapshot(
        entry_id="shipped-config",
        quotation_text="A quiet moment.",
        quotation_identity="A quiet moment.",
        source="A collection",
        attribution="An author",
        presentation_style="centered",
        font=None,
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule={
            "quotation": config.day_start.strftime("%H:%M"),
            "source": config.reveal.source.strftime("%H:%M"),
            "attribution": config.reveal.attribution.strftime("%H:%M"),
        },
        scheduling=SchedulingContext(date(2026, 11, 14), config.day_start.strftime("%H:%M")),
    )
    stages = resolve_reveal_stages(snapshot)
    images = prepare_daily_images(snapshot, stages, config, config.required_output_specifications, chooser=Random(0))
    try:
        assert set(images) == set(config.required_output_specifications)
        for specification, variants in images.items():
            assert len(variants) == len(stages)
            assert all(image.mode == "RGB" and image.size == specification.requested_output_size for image in variants)
    finally:
        for variants in images.values():
            for image in variants:
                image.close()
    assert not [record.message for record in caplog.records if record.levelno >= 30]


@pytest.mark.parametrize("duration", [0, 1, 60, 300])
def test_information_view_duration_accepts_inclusive_integer_range(tmp_path: Path, duration: int) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(presentation={"information_view": {"duration": duration}}),
        )
    )

    assert config.information_view_duration == duration


@pytest.mark.parametrize("duration", [True, False, "60", 1.5, -1, 301])
def test_invalid_information_view_duration_warns_and_uses_default(tmp_path: Path, duration: object, caplog) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(presentation={"information_view": {"duration": duration}}),
        )
    )

    assert config.information_view_duration == 60
    assert "presentation.information_view.duration" in caplog.text
    assert "using the documented default 60" in caplog.text


def test_information_view_duration_defaults_when_mapping_or_field_is_omitted(tmp_path: Path) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))
    explicit_empty = load_application_config(
        write_config(
            tmp_path / "explicit-empty.yaml",
            configuration_data(presentation={"information_view": {}}),
        )
    )

    assert config.information_view_duration == explicit_empty.information_view_duration == 60


def test_recognizes_reserved_waveshare_backend(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(destinations=[{"id": "epaper", "type": "waveshare-13in3-e"}]),
        )
    )

    assert config.display_backends[0].type == "waveshare-13in3-e"


@pytest.mark.parametrize("backend_type", ["window", "waveshare-13in3-e"])
def test_single_destination_backend_capacity_is_checked_during_configuration_validation(
    tmp_path: Path, backend_type: str
) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            destinations=[
                {"id": "first", "type": backend_type},
                {"id": "second", "type": backend_type},
            ]
        ),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any("supports at most 1 destination" in item.message for item in error.value.diagnostics)


def test_image_server_destinations_are_registered_without_enabling_the_service(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(destinations=[{"id": "kitchen", "type": "image-server"}]),
        )
    )

    backend = config.display_backends[0]
    assert backend.type == "image-server"
    assert not backend.service_enabled
    assert backend.host == "127.0.0.1"
    assert backend.port == 8080
    assert backend.outputs[0].identifier == "kitchen"
    assert backend.outputs[0].output_specification == ResolvedOutputSpecification("16:10", (3840, 2400))


@pytest.mark.parametrize("section", [None, {}, {"host": "127.0.0.1", "port": 8080}])
def test_present_image_server_section_enables_service_with_defaults(
    tmp_path: Path, caplog, section: dict[str, object]
) -> None:
    with caplog.at_level("INFO"):
        config = load_application_config(
            write_config(
                tmp_path / "config.yaml",
                configuration_data(
                    destinations=[{"id": "kitchen", "type": "image-server"}],
                    **{"image-server": section},
                ),
            )
        )

    assert config.display_backends[0].service_enabled
    assert config.display_backends[0].host == "127.0.0.1"
    assert config.display_backends[0].port == 8080
    assert "image-server:" not in caplog.text


def test_image_server_service_settings_are_independent_of_destinations(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[
                    {"id": "kitchen", "type": "image-server"},
                    {"id": "hallway", "type": "image-server", "aspect_ratio": "4:3", "resolution": [1600, 1200]},
                ],
                **{"image-server": {"host": "0.0.0.0", "port": 8123}},
            ),
        )
    )

    assert len(config.display_backends) == 1
    backend = config.display_backends[0]
    assert backend.service_enabled
    assert backend.host == "0.0.0.0"
    assert backend.port == 8123
    assert [output.identifier for output in backend.outputs] == ["kitchen", "hallway"]
    assert backend.outputs[1].output_specification == ResolvedOutputSpecification("4:3", (1600, 1200))
    assert len(config.required_output_specifications) == 2


@pytest.mark.parametrize("identifier", ["", " ", None, 1, "-bad", "_bad", "bad name", "é", "id:part"])
def test_destination_ids_require_url_safe_ascii_identifier_syntax(tmp_path: Path, identifier: object) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(destinations=[{"id": identifier, "type": "image-server"}]),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "destinations[0].id" for item in error.value.diagnostics)


def test_destination_id_length_limit_and_literal_all(tmp_path: Path) -> None:
    identifier = "a" * 256
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            destinations=[
                {"id": identifier, "type": "image-server"},
                {"id": "all", "type": "window"},
            ]
        ),
    )

    config = load_application_config(config_path)
    assert {output.identifier for backend in config.display_backends for output in backend.outputs} == {
        identifier,
        "all",
    }

    write_config(
        config_path,
        configuration_data(destinations=[{"id": identifier + "a", "type": "image-server"}]),
    )
    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(
        item.field == "destinations[0].id" and "at most 256 characters" in item.message
        for item in error.value.diagnostics
    )


def test_destination_ids_must_be_unique_across_backend_types(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            destinations=[
                {"id": "room", "type": "image-server"},
                {"id": "room", "type": "window"},
            ]
        ),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "destinations[1].id" for item in error.value.diagnostics)


def test_destination_ids_are_isolated_from_resource_identifier_namespaces(tmp_path: Path) -> None:
    identifier = "shared"
    write_font_bundle(tmp_path / "assets" / "fonts" / identifier, identifier)
    background = tmp_path / "assets" / "backgrounds" / f"{identifier}.png"
    background.parent.mkdir(parents=True)
    Image.new("RGB", (8, 6)).save(background)
    decoration_root = tmp_path / "assets" / "decorations" / identifier
    decoration_root.mkdir(parents=True)
    Image.new("RGBA", (8, 6)).save(decoration_root / "layer.png")
    write_asset_manifest(
        decoration_root,
        "decoration.yaml",
        {"format": 1, "id": identifier, "layers": [{"image": "layer.png"}]},
    )
    data = configuration_data(
        destinations=[{"id": identifier, "type": "window"}],
        palette={identifier: "#718C23"},
    )
    data.update(
        {
            "fonts": {"pools": {"default": [identifier], identifier: [identifier]}},
            "backgrounds": {"pools": {"default": [identifier], identifier: [identifier]}},
            "decorations": {
                "pools": {"default": [identifier], identifier: [identifier]},
                "colors": {"pools": {"default": [identifier], identifier: [identifier]}},
            },
            "text": {
                "min_font_size": 28,
                "max_font_size": 100,
                "colors": {"pools": {"default": [identifier]}},
            },
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.display_backends[0].outputs[0].identifier == identifier
    assert identifier in config.fonts
    assert identifier in config.backgrounds
    assert identifier in config.decorations
    assert config.palette[identifier] == "#718C23"
    assert config.font_pools[identifier] == (identifier,)
    assert config.background_pools[identifier] == (identifier,)
    assert config.decoration_pools[identifier] == (identifier,)


@pytest.mark.parametrize(
    "fields",
    [{"aspect_ratio": "4:3"}, {"resolution": [1600, 1200]}],
)
def test_image_server_output_overrides_must_be_paired(tmp_path: Path, fields: dict[str, object]) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(destinations=[{"id": "kitchen", "type": "image-server", **fields}]),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "destinations[0]" for item in error.value.diagnostics)


def test_image_server_outputs_resolve_independently_and_share_duplicate_specifications(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[
                    {"id": "desktop", "type": "window"},
                    {"id": "default", "type": "image-server"},
                    {"id": "wide", "type": "image-server", "aspect_ratio": "16:9", "resolution": [1920, 1080]},
                    {
                        "id": "portrait-ish",
                        "type": "image-server",
                        "aspect_ratio": "4:3",
                        "resolution": [1600, 1200],
                    },
                ]
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
        ({"unknown": 1}, "image-server.unknown"),
        ({"host": ""}, "image-server.host"),
        ({"host": "not a hostname"}, "image-server.host"),
        ({"host": True}, "image-server.host"),
        ({"port": True}, "image-server.port"),
        ({"port": "8080"}, "image-server.port"),
        ({"port": 0}, "image-server.port"),
        ({"port": 65536}, "image-server.port"),
    ],
)
def test_invalid_image_server_settings_are_recoverable(
    tmp_path: Path, image_server: object, expected_field: str, caplog
) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                destinations=[{"id": "desktop", "type": "window"}],
                **{"image-server": image_server},
            ),
        )
    )

    assert expected_field in caplog.text
    assert config.display_backends[0].host == "127.0.0.1"
    assert config.display_backends[0].port == 8080


@pytest.mark.parametrize(
    ("destinations", "expected_message"),
    [
        (None, "is required"),
        ([], "nonempty sequence"),
        ("bad", "nonempty sequence"),
        ([{"id": "desktop", "type": "unknown"}], "supported backends"),
        (
            [{"id": "one", "type": "window"}, {"id": "two", "type": "window"}],
            "supports at most 1 destination",
        ),
    ],
)
def test_required_and_invalid_destinations_are_rejected(
    tmp_path: Path, destinations: object, expected_message: str
) -> None:
    data = configuration_data(destinations=destinations)
    config_path = write_config(tmp_path / "config.yaml", data)

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    diagnostic = next(item for item in error.value.diagnostics if item.severity >= 40)
    assert expected_message in diagnostic.message


def test_non_mapping_destination_entry_is_diagnosed(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(destinations=[{"id": "desktop", "type": "window"}, None]),
    )

    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(config_path)

    assert any(item.field == "destinations[1]" for item in error.value.diagnostics)


def test_optional_mappings_default_and_absolute_paths_are_preserved(tmp_path: Path) -> None:
    absolute_content = tmp_path / "absolute-content"
    data = configuration_data(
        storage={"content": str(absolute_content)},
        scheduling={"reveal": {"source": "08:00"}},
    )
    config = load_application_config(write_config(tmp_path / "nested" / "config.yaml", data))

    assert config.content_directory == absolute_content
    assert config.day_start == time(5)
    assert config.reveal.source == time(8)
    assert config.reveal.attribution == time(18)
    assert config.default_fonts == ("test-font",)


def test_reveal_times_at_display_day_boundaries_are_valid(tmp_path: Path) -> None:
    data = configuration_data(
        scheduling={"day_start": "23:59", "reveal": {"source": "23:59", "attribution": "23:59"}},
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.day_start == time(23, 59)
    assert config.reveal.source == time(23, 59)
    assert config.reveal.attribution == time(23, 59)


def test_user_font_is_resolved_and_retained_outside_default_pool(tmp_path: Path) -> None:
    package = tmp_path / "assets" / "fonts" / "extra"
    user_font = write_font_bundle(package, "extra")
    data = configuration_data()

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.fonts["extra"].path == user_font
    assert not config.fonts["extra"].bundled
    assert config.default_fonts == ("test-font",)


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
    write_font_bundle(font.parent, "family")
    Image.new("RGB", (1600, 1200)).save(background)
    Image.new("RGBA", (1600, 1200)).save(decoration)
    write_asset_manifest(font.parent, "font.yaml", {"format": 1, "id": "family", "faces": {"regular": "Regular.ttf"}})
    write_asset_manifest(
        decoration.parent,
        "decoration.yaml",
        {"format": 1, "id": "border", "layers": [{"image": "Border.png", "method": "contain"}]},
    )

    data = configuration_data(storage={"content": "entries"})
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
    data = configuration_data()

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
    valid_package = tmp_path / "assets" / "fonts" / "valid-user-font"
    write_font_bundle(valid_package, "valid-user-font")
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
            configuration_data(fonts={"pools": {"default": ["valid-user-font", "missing-user-font"]}}),
        )
    )

    assert "valid-user-font" in config.fonts
    assert "missing-user-font" not in config.fonts
    assert config.default_fonts == ("valid-user-font",)
    assert "missing-user-font" in caplog.text
    assert "excluded" in caplog.text


def test_non_string_configuration_keys_are_warned_and_ignored(tmp_path: Path, caplog) -> None:
    config_data = configuration_data(
        scheduling={"day_start": "05:00", 1: "ignored", "unknown": "ignored"},
        fonts={"pools": {"default": ["test-font"]}, "available": {1: "ignored.ttf"}},
    )
    config = load_application_config(write_config(tmp_path / "config.yaml", config_data))

    assert config.default_fonts == ("test-font",)
    assert 1 not in config.fonts
    assert "scheduling[1]" in caplog.text
    assert "scheduling.unknown" in caplog.text
    assert "fonts.available: is not a supported configuration field" in caplog.text
    assert "ignored" in caplog.text


@pytest.mark.parametrize(
    ("insets", "expected_field"),
    [
        ({}, "presentation.insets.left"),
        ({"left": -1, "right": 384, "top": 324, "bottom": 324}, "presentation.insets.left"),
        ({"left": True, "right": 384, "top": 324, "bottom": 324}, "presentation.insets.left"),
        ({"left": 1.5, "right": 384, "top": 324, "bottom": 324}, "presentation.insets.left"),
        ({"left": 1920, "right": 1920, "top": 324, "bottom": 324}, "presentation.insets"),
        ({"left": 384, "right": 384, "top": 1080, "bottom": 1080}, "presentation.insets"),
    ],
)
def test_invalid_presentation_insets_are_rejected(
    tmp_path: Path, insets: dict[str, int | float | bool], expected_field: str
) -> None:
    data = configuration_data(presentation={"insets": insets})

    assert expected_field in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_presentation_insets_accept_zero_edges(tmp_path: Path) -> None:
    data = configuration_data(presentation={"insets": {"left": 0, "right": 0, "top": 0, "bottom": 0}})

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.presentation_insets == PresentationInsets(0, 0, 0, 0)


def test_global_insets_are_validated_against_configured_destination_aspects(tmp_path: Path) -> None:
    insets = {"left": 1650, "right": 1650, "top": 324, "bottom": 324}
    destinations = [
        {
            "id": "desktop",
            "type": "window",
            "audience": "private",
            "aspect_ratio": "16:10",
            "resolution": [320, 200],
        }
    ]
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(destinations=destinations, presentation={"insets": insets}),
    )

    assert load_application_config(config_path).presentation_insets == PresentationInsets(1650, 1650, 324, 324)

    destinations.append(
        {
            "id": "web",
            "type": "publish",
            "audience": "private",
            "aspect_ratio": "5:3",
            "resolution": [320, 192],
        }
    )
    config_path.write_text(
        yaml.safe_dump(configuration_data(destinations=destinations, presentation={"insets": insets}), sort_keys=False),
        encoding="utf-8",
    )

    assert load_application_config(config_path).presentation_insets == PresentationInsets(1650, 1650, 324, 324)

    destinations.append(
        {
            "id": "web-4-3",
            "type": "publish",
            "audience": "private",
            "aspect_ratio": "4:3",
            "resolution": [320, 240],
        }
    )
    config_path.write_text(
        yaml.safe_dump(configuration_data(destinations=destinations, presentation={"insets": insets}), sort_keys=False),
        encoding="utf-8",
    )

    assert "presentation.insets" in diagnostic_fields(config_path)


def test_decoration_insets_follow_configured_aspects_and_revalidate(tmp_path: Path, caplog) -> None:
    decoration_root = tmp_path / "assets" / "decorations"
    for identifier, insets in (
        ("valid", None),
        ("aspect-specific", {"left": 1650, "right": 1650, "top": 324, "bottom": 324}),
    ):
        package = decoration_root / identifier
        package.mkdir(parents=True)
        Image.new("RGBA", (16, 16)).save(package / "overlay.png")
        manifest: dict[str, object] = {
            "format": 1,
            "id": identifier,
            "layers": [{"image": "overlay.png", "method": "contain"}],
        }
        if insets is not None:
            manifest["presentation_insets"] = insets
        write_asset_manifest(package, "decoration.yaml", manifest)

    destinations = [
        {
            "id": "desktop",
            "type": "window",
            "audience": "private",
            "aspect_ratio": "16:10",
            "resolution": [320, 200],
        }
    ]
    data = configuration_data(
        destinations=destinations,
        decorations={"pools": {"default": ["valid", "aspect-specific"]}},
    )
    config_path = write_config(tmp_path / "config.yaml", data)

    configuration = load_application_config(config_path)

    assert {"valid", "aspect-specific"} <= set(configuration.decorations)

    destinations.append(
        {
            "id": "web-4-3",
            "type": "publish",
            "audience": "private",
            "aspect_ratio": "4:3",
            "resolution": [320, 240],
        }
    )
    data = configuration_data(
        destinations=destinations,
        decorations={"pools": {"default": ["valid", "aspect-specific"]}},
    )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    configuration = load_application_config(config_path)

    assert "valid" in configuration.decorations
    assert "aspect-specific" not in configuration.decorations
    assert "aspect-specific/decoration.yaml.presentation_insets" in caplog.text.replace("\\", "/")
    assert "4:3 design canvas" in caplog.text
    assert "this decoration is excluded" in caplog.text


@pytest.mark.parametrize(
    ("data", "expected_field"),
    [
        (
            configuration_data(presentation={"insets": {"left": 3840, "right": 0, "top": 0, "bottom": 0}}),
            "presentation.insets",
        ),
        (
            configuration_data(presentation={"insets": {"left": True, "right": 384, "top": 324, "bottom": 324}}),
            "presentation.insets.left",
        ),
        (
            configuration_data(text={"min_font_size": 10, "max_font_size": 9}),
            "text.max_font_size",
        ),
        (
            configuration_data(fonts={"pools": {"default": []}}),
            "fonts.pools.default",
        ),
    ],
)
def test_invalid_required_fields_are_fatal(tmp_path: Path, data: dict[str, object], expected_field: str) -> None:
    fields = diagnostic_fields(write_config(tmp_path / "config.yaml", data))

    assert expected_field in fields


def test_omitted_optional_defaults_are_silent(tmp_path: Path, caplog) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        {
            "destinations": [{"id": "desktop", "type": "window", "audience": "private"}],
            "fonts": {"pools": {"default": ["test-font"]}},
        },
    )

    with caplog.at_level(logging.INFO):
        config = load_application_config(config_path)

    assert config.day_start == time(5)
    assert config.reveal.source == time(12)
    assert config.reveal.attribution == time(18)
    assert config.content_directory == tmp_path / "content"
    assert config.presentation_insets == PresentationInsets(384, 384, 324, 324)
    assert config.information_view_duration == 60
    assert (config.min_font_size, config.max_font_size) == (56, 200)
    assert config.default_backgrounds == ("none",)
    assert config.default_decorations == ("none",)
    assert config.default_text_colors == ("black",)
    assert config.default_decoration_colors == ("black",)
    assert not [record for record in caplog.records if record.levelno >= logging.INFO]


def test_invalid_optional_values_are_reported_without_default_announcements(tmp_path: Path, caplog) -> None:
    config_path = write_config(
        tmp_path / "config.yaml",
        configuration_data(
            scheduling={
                "timezone": "UTC",
                "day_start": "6:00",
                "unknown": True,
                "reveal": {"quotation": "00:00", "source": "invalid"},
            },
            unexpected=True,
        ),
    )

    with caplog.at_level("INFO"):
        config = load_application_config(config_path)

    assert config.day_start == time(5)
    assert config.reveal.source == time(12)
    assert not [record for record in caplog.records if record.levelno == logging.INFO]
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any("scheduling.day_start" in message and "default '05:00'" in message for message in warnings)
    assert any("scheduling.reveal.source" in message and "default '12:00'" in message for message in warnings)
    assert "scheduling.day_start" in caplog.text
    assert "scheduling.timezone" in caplog.text
    assert "scheduling.reveal.quotation" in caplog.text
    assert "is not a supported configuration field; it is ignored" in caplog.text
    assert "scheduling.reveal.source" in caplog.text
    assert "unexpected" in caplog.text
    assert "using" in caplog.text and "ignored" in caplog.text


def test_fatal_configuration_error_is_logged(tmp_path: Path, caplog) -> None:
    config_path = write_config(tmp_path / "config.yaml", {"fonts": {"pools": {"default": ["test-font"]}}})

    with caplog.at_level(logging.INFO), pytest.raises(ApplicationConfigurationError):
        load_application_config(config_path)

    assert any(
        record.levelno == logging.ERROR
        and str(config_path) in record.getMessage()
        and "destinations" in record.getMessage()
        and "required" in record.getMessage()
        for record in caplog.records
    )
    assert not [record for record in caplog.records if record.levelno == logging.INFO]


@pytest.mark.parametrize(
    ("default_fonts", "expected"),
    [
        (["test-font", "test-font"], ("test-font",)),
        (["test-font", "unavailable"], ("test-font",)),
        (["second-font", "test-font", "second-font"], ("second-font", "test-font")),
        (["unavailable"], ()),
    ],
)
def test_default_font_pool_filters_unavailable_and_duplicates(
    tmp_path: Path, default_fonts: list[str], expected: tuple[str, ...], caplog
) -> None:
    write_font_bundle(tmp_path / "assets" / "fonts" / "second-font", "second-font")
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(fonts={"pools": {"default": default_fonts}}),
        )
    )

    assert config.default_fonts == expected
    if len(default_fonts) != len(expected):
        assert "ignored" in caplog.text or "excluded" in caplog.text


@pytest.mark.parametrize(
    "contents",
    [
        "scheduling: [not, a, mapping",
        "- one\n- two\n",
        "scheduling: &shared {day_start: '05:00'}\nstorage: *shared\n",
        "scheduling:\n  day_start: '05:00'\n  day_start: '06:00'\n",
        "scheduling:\n  day_start: '05:00'\n---\nscheduling:\n  day_start: '05:00'\n",
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
    baseline = load_application_config(write_config(tmp_path / "baseline.yaml", configuration_data()))
    bundled_font = next(font for font in baseline.fonts.values() if font.bundled)
    bundled_font_identifier = bundled_font.identifier
    font_bytes = bundled_font.path.read_bytes()
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
        {"format": 1, "id": bundled_font_identifier, "faces": {"regular": "Regular.ttf"}},
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

    assert config.fonts[bundled_font_identifier].bundled
    assert "duplicate" not in config.fonts
    assert "missing" not in config.fonts
    assert "invalid" not in config.fonts
    assert f"conflicts with bundled identifier {bundled_font_identifier!r}" in caplog.text
    assert "share identifier 'duplicate'; all are excluded" in caplog.text
    assert "resource path is missing" in caplog.text
    assert "unsupported by Pillow" in caplog.text


def test_unreadable_user_font_is_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    package = tmp_path / "assets" / "fonts" / "extra"
    package.mkdir(parents=True)
    user_font = package / "font.ttf"
    user_font.write_bytes(write_font_bundle(package, "extra").read_bytes())
    data = configuration_data()
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

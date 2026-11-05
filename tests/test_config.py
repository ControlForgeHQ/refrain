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

from refrain import ApplicationConfigurationError, BackgroundResource, load_application_config, load_background_image


def configuration_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "general": {"timezone": "America/Toronto"},
        "content": {"directory": "content"},
        "display": {"backends": [{"type": "window"}]},
        "layout": {
            "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
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


def diagnostic_fields(path: Path) -> tuple[str, ...]:
    with pytest.raises(ApplicationConfigurationError) as error:
        load_application_config(path)
    assert all(str(path) in str(diagnostic) for diagnostic in error.value.diagnostics)
    return tuple(diagnostic.field for diagnostic in error.value.diagnostics)


def background_configuration(**settings: object) -> dict[str, object]:
    data = configuration_data()
    data["layout"]["backgrounds"] = settings
    return data


def test_bundled_background_registry_and_plain_default(tmp_path: Path, caplog) -> None:
    config = load_application_config(write_config(tmp_path / "config.yaml", configuration_data()))

    assert set(config.backgrounds) == {"aged-paper", "canvas", "cloth", "ethereal", "hex"}
    assert config.default_backgrounds == ("none",)
    assert all(resource.bundled for resource in config.backgrounds.values())
    assert not any(record.levelno >= 30 and "background" in record.message for record in caplog.records)
    for identifier, resource in config.backgrounds.items():
        assert resource.identifier == identifier
        assert resource.path.name == f"{identifier}.png"
        with load_background_image(resource) as image:
            assert image.size == (1600, 1200)
            assert image.mode in {"RGB", "RGBA"}
    with pytest.raises(TypeError):
        config.backgrounds["other"] = config.backgrounds["canvas"]


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
@pytest.mark.parametrize("absolute", [True, False])
def test_custom_background_paths_and_modes(tmp_path: Path, mode: str, absolute: bool) -> None:
    path = tmp_path / "paper.png"
    Image.new(mode, (1600, 1200)).save(path)
    path_value = str(path) if absolute else path.name
    data = background_configuration(available={"paper": path_value}, default=["paper"])

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.backgrounds["paper"] == BackgroundResource("paper", path, False)
    assert config.default_backgrounds == ("paper",)
    with load_background_image(config.backgrounds["paper"]) as image:
        assert image.mode == mode
        assert image.getpixel((0, 0)) == ((0, 0, 0) if mode == "RGB" else (0, 0, 0, 0))


@pytest.mark.parametrize("kind", ["jpeg", "palette", "gray", "size", "animation", "corrupt", "missing", "truncated"])
def test_invalid_backgrounds_excluded_independently(tmp_path: Path, kind: str, caplog) -> None:
    bad_path = tmp_path / "bad.png"
    good_path = tmp_path / "good.png"
    Image.new("RGB", (1600, 1200)).save(good_path)
    if kind == "jpeg":
        Image.new("RGB", (1600, 1200)).save(bad_path, format="JPEG")
    elif kind in {"palette", "gray"}:
        Image.new("P" if kind == "palette" else "L", (1600, 1200)).save(bad_path)
    elif kind == "size":
        Image.new("RGB", (1200, 1600)).save(bad_path)
    elif kind == "animation":
        Image.new("RGBA", (1600, 1200)).save(
            bad_path, save_all=True, append_images=[Image.new("RGBA", (1600, 1200), "red")], duration=100
        )
    elif kind == "corrupt":
        bad_path.write_bytes(b"not an image")
    elif kind == "truncated":
        bad_path.write_bytes(good_path.read_bytes()[:100])
    data = background_configuration(available={"bad": "bad.png", "good": "good.png"}, default=["bad", "good"])

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert "bad" not in config.backgrounds
    assert "good" in config.backgrounds
    assert config.default_backgrounds == ("good",)
    assert "layout.backgrounds.available.bad" in caplog.text
    assert "excluded" in caplog.text


@pytest.mark.parametrize("identifier", ["none", "aged-paper", "canvas", "cloth", "ethereal", "hex"])
def test_reserved_background_identifiers_cannot_be_overridden(tmp_path: Path, identifier: str, caplog) -> None:
    data = background_configuration(available={identifier: "missing.png"})

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

    assert set(config.backgrounds) == {"aged-paper", "canvas", "cloth", "ethereal", "hex"}
    assert "layout.backgrounds.available" in caplog.text


def test_default_background_pool_deduplicates_and_excludes_invalid_values(tmp_path: Path, caplog) -> None:
    data = background_configuration(default=["canvas", "none", "canvas", None, False, "", " ", "Canvas", "hex", "none"])

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.default_backgrounds == ("canvas", "none", "hex")
    assert "background identifier 'Canvas' is unavailable" in caplog.text
    assert "must be a nonempty background identifier" in caplog.text


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
    background_path = tmp_path / "paper.png"
    Image.new("RGB", (1600, 1200)).save(background_path)
    config_path = write_config(
        tmp_path / "config.yaml", background_configuration(available={"paper": "paper.png"}, default=["paper"])
    )
    original_open = Path.open

    def deny_background_read(path: Path, *args, **kwargs):
        if path == background_path:
            raise PermissionError("background read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_background_read)

    config = load_application_config(config_path)

    assert "paper" not in config.backgrounds
    assert config.default_backgrounds == ("none",)
    assert "layout.backgrounds.available.paper" in caplog.text
    assert "background read denied" in caplog.text


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

    assert config.timezone.key == "America/Toronto"
    assert [backend.type for backend in config.display_backends] == ["window"]
    assert config.day_start == time(6)
    assert config.content_directory == tmp_path / "content"
    assert config.reveal.source == time(12)
    assert config.reveal.attribution == time(18)
    assert config.presentation_region.x == 0.1
    assert config.presentation_region.y == 0.15
    assert config.presentation_region.width == 0.8
    assert config.presentation_region.height == 0.55
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


def test_content_directory_default_is_configuration_relative(tmp_path: Path) -> None:
    data = configuration_data()
    data.pop("content")

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.content_directory == tmp_path / "content"


def test_representative_configuration_example_loads() -> None:
    config = load_application_config(Path(__file__).parent.parent / "examples" / "config.yaml")

    assert [backend.type for backend in config.display_backends] == ["window", "image-server"]
    assert config.default_fonts == ("libre-baskerville", "lora", "source-sans-3")
    assert config.information_view_duration == 60


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
                configuration_data(display={"backends": [{"type": "image-server"}]}),
            )
        )
    configured = load_application_config(
        write_config(
            tmp_path / "configured.yaml",
            configuration_data(
                display={
                    "backends": [{"type": "image-server", "host": "0.0.0.0", "port": 8123}],
                }
            ),
        )
    )

    assert "display.backends[0].host" in caplog.text
    assert "display.backends[0].port" in caplog.text
    assert default_config.display_backends[0].host == "127.0.0.1"
    assert default_config.display_backends[0].port == 8080
    assert configured.display_backends[0].host == "0.0.0.0"
    assert configured.display_backends[0].port == 8123


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
                        {"type": "image-server", **image_server},
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
    user_font = tmp_path / "fonts" / "additional.font"
    user_font.parent.mkdir()
    with source_font.open("rb") as source, user_font.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    data = configuration_data(
        layout={
            "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "fonts": {"default": ["lora"], "available": {"extra": "fonts/additional.font"}},
            "text": {"min_font_size": 28, "max_font_size": 100},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.fonts["extra"].path == user_font
    assert not config.fonts["extra"].bundled
    assert config.default_fonts == ("lora",)


def test_absolute_user_font_path_is_preserved(tmp_path: Path) -> None:
    source_font = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
    user_font = tmp_path / "custom-font.ttf"
    with source_font.open("rb") as source, user_font.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    data = configuration_data(
        layout={
            "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "fonts": {"default": ["lora"], "available": {"extra": str(user_font)}},
            "text": {"min_font_size": 28, "max_font_size": 100},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.fonts["extra"].path == user_font


def test_mixed_user_font_registrations_keep_only_usable_fonts(tmp_path: Path, caplog) -> None:
    source_font = files("refrain").joinpath("assets", "fonts", "source-sans-3", "SourceSans3-Regular.ttf")
    valid_font = tmp_path / "valid.ttf"
    valid_font.write_bytes(source_font.read_bytes())
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(
                layout={
                    "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
                    "fonts": {
                        "default": ["valid-user-font", "missing-user-font"],
                        "available": {
                            "valid-user-font": str(valid_font),
                            "missing-user-font": str(tmp_path / "missing.ttf"),
                        },
                    },
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
            "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "fonts": {"default": ["lora"], "available": {1: "ignored.ttf"}},
            "text": {"min_font_size": 28, "max_font_size": 100},
        },
    )
    config = load_application_config(write_config(tmp_path / "config.yaml", config_data))

    assert config.timezone.key == "UTC"
    assert config.default_fonts == ("lora",)
    assert 1 not in config.fonts
    assert "general[1]" in caplog.text
    assert "layout.fonts.available[1]" in caplog.text
    assert "ignored" in caplog.text


@pytest.mark.parametrize(
    ("region", "expected_field"),
    [
        ({}, "layout.presentation_region.x"),
        ({"x": -0.1, "y": 0.1, "width": 0.2, "height": 0.2}, "layout.presentation_region.x"),
        ({"x": 0.1, "y": 1, "width": 0.2, "height": 0.2}, "layout.presentation_region.y"),
        ({"x": 0.1, "y": 0.1, "width": 0, "height": 0.2}, "layout.presentation_region.width"),
        ({"x": 0.1, "y": 0.1, "width": 0.2, "height": 0}, "layout.presentation_region.height"),
        ({"x": 0.1, "y": 0.8, "width": 0.2, "height": 0.3}, "layout.presentation_region.height"),
    ],
)
def test_invalid_presentation_region_geometry_is_rejected(
    tmp_path: Path, region: dict[str, float], expected_field: str
) -> None:
    data = configuration_data(
        layout={
            "presentation_region": region,
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 1, "max_font_size": 2},
        }
    )

    assert expected_field in diagnostic_fields(write_config(tmp_path / "config.yaml", data))


def test_presentation_region_accepts_full_normalized_image(tmp_path: Path) -> None:
    data = configuration_data(
        layout={
            "presentation_region": {"x": 0, "y": 0, "width": 1, "height": 1},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 1, "max_font_size": 2},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.presentation_region.x == 0
    assert config.presentation_region.y == 0
    assert config.presentation_region.width == 1
    assert config.presentation_region.height == 1


def test_unsupported_layout_field_is_ignored_with_warning(tmp_path: Path, caplog) -> None:
    data = configuration_data(
        layout={
            "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "quotation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "fonts": {"default": ["lora"]},
            "text": {"min_font_size": 1, "max_font_size": 2},
        }
    )

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.presentation_region.x == 0.1
    assert "layout.quotation_region" in caplog.text
    assert "ignored" in caplog.text


@pytest.mark.parametrize(
    ("data", "expected_field"),
    [
        ({"general": {}}, "general.timezone"),
        (configuration_data(general={"timezone": True}), "general.timezone"),
        (configuration_data(general={"timezone": "Not/A_Zone"}), "general.timezone"),
        (configuration_data(general={"timezone": "localtime"}), "general.timezone"),
        (configuration_data(general={"timezone": "EST"}), "general.timezone"),
        (
            configuration_data(
                layout={
                    "presentation_region": {"x": 0.8, "y": 0.1, "width": 0.3, "height": 0.5},
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 1, "max_font_size": 2},
                }
            ),
            "layout.presentation_region.width",
        ),
        (
            configuration_data(
                layout={
                    "presentation_region": {"x": True, "y": 0.1, "width": 0.3, "height": 0.5},
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 1, "max_font_size": 2},
                }
            ),
            "layout.presentation_region.x",
        ),
        (
            configuration_data(
                layout={
                    "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.5},
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 10, "max_font_size": 9},
                }
            ),
            "layout.text.max_font_size",
        ),
        (
            configuration_data(
                layout={
                    "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.5},
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
                    "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
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


def test_user_font_collisions_missing_files_and_unsupported_files_are_excluded(tmp_path: Path, caplog) -> None:
    for identifier, font_path in (
        ("lora", "missing.ttf"),
        ("not-a-font", "missing.ttf"),
        ("not-a-font", "invalid.ttf"),
    ):
        if font_path == "invalid.ttf":
            (tmp_path / font_path).write_bytes(b"not a font")
        data = configuration_data(
            layout={
                "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
                "fonts": {"default": ["lora"], "available": {identifier: font_path}},
                "text": {"min_font_size": 28, "max_font_size": 100},
            }
        )

        config = load_application_config(write_config(tmp_path / "config.yaml", data))

        assert "layout.fonts.available." + identifier in caplog.text
        assert config.fonts["lora"].bundled
        assert (identifier in config.fonts) == (identifier == "lora")


def test_unreadable_user_font_is_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    user_font = tmp_path / "font.ttf"
    user_font.write_bytes(files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf").read_bytes())
    data = configuration_data(
        layout={
            "presentation_region": {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            "fonts": {"default": ["lora"], "available": {"extra": str(user_font)}},
            "text": {"min_font_size": 28, "max_font_size": 100},
        }
    )
    config_path = write_config(tmp_path / "config.yaml", data)
    original_open = Path.open

    def deny_font_read(path: Path, *args: object, **kwargs: object):
        if path == user_font:
            raise PermissionError("permission denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_font_read)

    config = load_application_config(config_path)
    assert "layout.fonts.available.extra" in caplog.text
    assert "extra" not in config.fonts

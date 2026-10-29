from __future__ import annotations

import shutil
from datetime import time
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from refrain import ApplicationConfigurationError, load_application_config


def configuration_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "general": {"timezone": "America/Toronto"},
        "content": {"directory": "content"},
        "display": {"backend": "window"},
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


def test_loads_defaults_and_bundled_font_resources(tmp_path: Path) -> None:
    config_path = write_config(tmp_path / "config.yaml", configuration_data())

    config = load_application_config(config_path)

    assert config.timezone.key == "America/Toronto"
    assert config.display_backend == "window"
    assert config.day_start == time(6)
    assert config.content_directory == tmp_path / "content"
    assert config.reveal.quotation == time(6)
    assert config.reveal.source == time(12)
    assert config.reveal.attribution == time(18)
    assert config.presentation_region.x == 0.1
    assert config.presentation_region.y == 0.15
    assert config.presentation_region.width == 0.8
    assert config.presentation_region.height == 0.55
    assert config.default_fonts == ("lora",)
    assert config.min_font_size == 28
    assert config.max_font_size == 100
    assert set(config.fonts) == {"libre-baskerville", "lora", "source-sans-3"}
    assert all(font.bundled for font in config.fonts.values())
    assert all(font.path.is_file() for font in config.fonts.values())
    assert all(font.path.parent.joinpath("OFL.txt").is_file() for font in config.fonts.values())


def test_content_directory_default_is_configuration_relative(tmp_path: Path) -> None:
    data = configuration_data()
    data.pop("content")

    config = load_application_config(write_config(tmp_path / "config.yaml", data))

    assert config.content_directory == tmp_path / "content"


def test_representative_configuration_example_loads() -> None:
    config = load_application_config(Path(__file__).parent.parent / "examples" / "config.yaml")

    assert config.display_backend == "window"
    assert config.default_fonts == ("libre-baskerville", "lora", "source-sans-3")


def test_recognizes_reserved_waveshare_backend(tmp_path: Path) -> None:
    config = load_application_config(
        write_config(tmp_path / "config.yaml", configuration_data(display={"backend": "waveshare-13in3-e"}))
    )

    assert config.display_backend == "waveshare-13in3-e"


def test_image_server_configuration_defaults_and_explicit_settings(tmp_path: Path, caplog) -> None:
    with caplog.at_level("INFO"):
        default_config = load_application_config(
            write_config(
                tmp_path / "default.yaml",
                configuration_data(display={"backend": "image-server"}),
            )
        )
    configured = load_application_config(
        write_config(
            tmp_path / "configured.yaml",
            configuration_data(
                display={
                    "backend": "image-server",
                    "image-server": {"host": "0.0.0.0", "port": 8123},
                }
            ),
        )
    )

    assert "display.image-server.host" in caplog.text
    assert "display.image-server.port" in caplog.text
    assert default_config.display_backend == "image-server"
    assert default_config.image_server_host == "127.0.0.1"
    assert default_config.image_server_port == 8080
    assert configured.image_server_host == "0.0.0.0"
    assert configured.image_server_port == 8123


@pytest.mark.parametrize(
    ("image_server", "expected_field"),
    [
        ([], "display.image-server"),
        ({"unknown": 1}, "display.image-server.unknown"),
        ({"host": ""}, "display.image-server.host"),
        ({"host": "not a hostname"}, "display.image-server.host"),
        ({"host": True}, "display.image-server.host"),
        ({"port": True}, "display.image-server.port"),
        ({"port": "8080"}, "display.image-server.port"),
        ({"port": 0}, "display.image-server.port"),
        ({"port": 65536}, "display.image-server.port"),
    ],
)
def test_invalid_image_server_settings_are_recoverable(
    tmp_path: Path, image_server: object, expected_field: str, caplog
) -> None:
    config = load_application_config(
        write_config(
            tmp_path / "config.yaml",
            configuration_data(display={"backend": "window", "image-server": image_server}),
        )
    )

    assert expected_field in caplog.text
    assert config.image_server_host == "127.0.0.1"
    assert config.image_server_port == 8080


@pytest.mark.parametrize(
    ("display", "expected_message"),
    [
        (None, "is required"),
        ({}, "is required"),
        ({"backend": "unknown"}, "supported backends"),
        ({"backend": 1}, "supported backends"),
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

    diagnostic = next(item for item in error.value.diagnostics if item.field == "display.backend")
    assert expected_message in diagnostic.message


def test_optional_mappings_default_and_absolute_paths_are_preserved(tmp_path: Path) -> None:
    absolute_content = tmp_path / "absolute-content"
    data = configuration_data(content={"directory": str(absolute_content)}, reveal={"source": "08:00"})
    config = load_application_config(write_config(tmp_path / "nested" / "config.yaml", data))

    assert config.content_directory == absolute_content
    assert config.day_start == time(6)
    assert config.reveal.quotation == time(6)
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
    assert config.reveal.quotation == time(23, 59)
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
            reveal={"quotation": "07:00", "source": "invalid"},
            unexpected=True,
        ),
    )

    with caplog.at_level("INFO"):
        config = load_application_config(config_path)

    assert config.day_start == time(6)
    assert config.reveal.quotation == time(6)
    assert config.reveal.source == time(12)
    assert "using documented defaults" in caplog.text
    assert "general.day_start" in caplog.text
    assert "reveal.quotation" in caplog.text
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

"""Load and validate Refrain application configuration."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import time
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import yaml
from PIL import ImageFont

from ._yaml import load_yaml, yaml_error_location

_TOP_LEVEL_FIELDS = {"general", "content", "reveal", "layout"}
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_TIMEZONE_ABBREVIATIONS = {
    "ADT",
    "AKDT",
    "AKST",
    "AST",
    "CDT",
    "CST",
    "EDT",
    "EST",
    "HDT",
    "HST",
    "MDT",
    "MST",
    "NDT",
    "NST",
    "PDT",
    "PST",
    "YST",
}
_NON_IANA_TIMEZONE_KEYS = {"localtime", "posixrules"}
_BUNDLED_FONT_FILES = {
    "libre-baskerville": ("assets", "fonts", "libre-baskerville", "LibreBaskerville-Regular.ttf"),
    "lora": ("assets", "fonts", "lora", "Lora-Regular.ttf"),
    "source-sans-3": ("assets", "fonts", "source-sans-3", "SourceSans3-Regular.ttf"),
}


@dataclass(frozen=True)
class ConfigurationDiagnostic:
    """A configuration validation issue tied to a file and field."""

    file: Path
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}: {self.field}: {self.message}"


class ApplicationConfigurationError(Exception):
    """Raised when an application configuration file cannot be accepted."""

    def __init__(self, diagnostics: tuple[ConfigurationDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(diagnostic) for diagnostic in diagnostics))


@dataclass(frozen=True)
class FontResource:
    """A validated bundled or user-registered Pillow-compatible font."""

    identifier: str
    path: Union[Path, Traversable]
    bundled: bool


@dataclass(frozen=True)
class RevealSchedule:
    """Validated global reveal times in the configured local timezone."""

    quotation: time
    source: time
    attribution: time


@dataclass(frozen=True)
class QuotationRegion:
    """Normalized rectangle reserved for the primary quotation."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class ApplicationConfiguration:
    """Validated, hardware-independent application configuration."""

    file: Path
    timezone: ZoneInfo
    day_start: time
    content_directory: Path
    reveal: RevealSchedule
    presentation_region: QuotationRegion
    fonts: Mapping[str, FontResource]
    default_fonts: tuple[str, ...]
    min_font_size: int
    max_font_size: int


def _known_fields(value: dict[str, object], allowed: set[str], field: str, report: Callable[[str, str], None]) -> None:
    for key in sorted(value.keys() - allowed):
        report(f"{field}.{key}" if field else key, "is not a supported configuration field")


def _mapping(value: object, field: str, report: Callable[[str, str], None]) -> dict[str, object]:
    if not isinstance(value, dict):
        report(field, "must be a mapping")
        return {}
    return value


def _parse_time(value: object, field: str, report: Callable[[str, str], None]) -> time | None:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        report(field, "must be a valid HH:MM local time")
        return None
    return time.fromisoformat(value)


def _load_font(path: Union[Path, Traversable], field: str, report: Callable[[str, str], None]) -> bool:
    try:
        with path.open("rb") as font_file:
            ImageFont.truetype(font_file, size=12)
    except Exception as error:
        report(field, f"must be an existing, readable font supported by Pillow: {error}")
        return False
    return True


def load_application_config(config_file: Union[str, Path]) -> ApplicationConfiguration:
    """Load and validate an application configuration YAML file.

    Validation is all-or-nothing. Relative content and user-font paths are
    resolved against the directory containing ``config_file``.
    """
    file = Path(config_file).absolute()
    diagnostics: list[ConfigurationDiagnostic] = []

    def report(field: str, message: str) -> None:
        diagnostics.append(ConfigurationDiagnostic(file=file, field=field, message=message))

    try:
        contents = file.read_text(encoding="utf-8")
        data = load_yaml(contents)
    except (OSError, UnicodeError) as error:
        report("$", f"cannot read UTF-8 YAML file: {error}")
        raise ApplicationConfigurationError(tuple(diagnostics)) from error
    except yaml.YAMLError as error:
        location = yaml_error_location(error)
        prefix = f"{location}: " if location else ""
        report("$", f"invalid or unsupported YAML: {prefix}{error}")
        raise ApplicationConfigurationError(tuple(diagnostics)) from error

    if not isinstance(data, dict):
        report("$", "must contain one top-level mapping")
        raise ApplicationConfigurationError(tuple(diagnostics))
    _known_fields(data, _TOP_LEVEL_FIELDS, "", report)

    general = _mapping(data.get("general", {}), "general", report)
    _known_fields(general, {"timezone", "day_start"}, "general", report)
    timezone_value = general.get("timezone")
    timezone: ZoneInfo | None = None
    if not isinstance(timezone_value, str) or not timezone_value:
        report("general.timezone", "is required and must be a valid IANA timezone identifier")
    elif timezone_value in _TIMEZONE_ABBREVIATIONS:
        report("general.timezone", "must be an IANA timezone identifier, not a timezone abbreviation")
    elif timezone_value in _NON_IANA_TIMEZONE_KEYS:
        report("general.timezone", "is not a portable IANA timezone identifier")
    elif timezone_value not in available_timezones():
        report("general.timezone", "is not a recognized IANA timezone identifier")
    else:
        try:
            timezone = ZoneInfo(timezone_value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            report("general.timezone", f"is not a valid IANA timezone identifier: {error}")

    day_start = _parse_time(general.get("day_start", "06:00"), "general.day_start", report)

    content = _mapping(data.get("content", {}), "content", report)
    _known_fields(content, {"directory"}, "content", report)
    directory_value = content.get("directory", "content")
    content_directory: Path | None = None
    if not isinstance(directory_value, str) or not directory_value:
        report("content.directory", "must be a nonempty path string")
    else:
        content_directory = Path(directory_value)
        if not content_directory.is_absolute():
            content_directory = file.parent / content_directory

    reveal_data = _mapping(data.get("reveal", {}), "reveal", report)
    _known_fields(reveal_data, {"quotation", "source", "attribution"}, "reveal", report)
    quotation_time = _parse_time(
        (
            reveal_data["quotation"]
            if "quotation" in reveal_data
            else (day_start.strftime("%H:%M") if day_start is not None else None)
        ),
        "reveal.quotation",
        report,
    )
    source_time = _parse_time(reveal_data.get("source", "12:00"), "reveal.source", report)
    attribution_time = _parse_time(reveal_data.get("attribution", "18:00"), "reveal.attribution", report)
    if "quotation" in reveal_data and quotation_time is not None and day_start is not None:
        if quotation_time != day_start:
            report("reveal.quotation", "must coincide with general.day_start")
    for field, reveal_time in (("reveal.source", source_time), ("reveal.attribution", attribution_time)):
        if reveal_time is not None and day_start is not None and reveal_time < day_start:
            report(field, "must not precede general.day_start on the display-day calendar date")
    reveal = (
        RevealSchedule(quotation_time, source_time, attribution_time)
        if quotation_time is not None and source_time is not None and attribution_time is not None
        else None
    )

    layout = _mapping(data.get("layout", {}), "layout", report)
    _known_fields(layout, {"presentation_region", "quotation_region", "fonts", "text"}, "layout", report)
    if "quotation_region" in layout:
        report("layout.quotation_region", "is obsolete; use layout.presentation_region instead")
    region_data = _mapping(layout.get("presentation_region", {}), "layout.presentation_region", report)
    _known_fields(region_data, {"x", "y", "width", "height"}, "layout.presentation_region", report)
    region_values: dict[str, float] = {}
    for field in ("x", "y", "width", "height"):
        value = region_data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            report(f"layout.presentation_region.{field}", "is required and must be a finite number")
        else:
            region_values[field] = float(value)
    if len(region_values) == 4:
        x, y, width, height = (
            region_values["x"],
            region_values["y"],
            region_values["width"],
            region_values["height"],
        )
        if not 0 <= x < 1:
            report("layout.presentation_region.x", "must satisfy 0 <= x < 1")
        if not 0 <= y < 1:
            report("layout.presentation_region.y", "must satisfy 0 <= y < 1")
        if not 0 < width <= 1:
            report("layout.presentation_region.width", "must satisfy 0 < width <= 1")
        if not 0 < height <= 1:
            report("layout.presentation_region.height", "must satisfy 0 < height <= 1")
        if x + width > 1:
            report("layout.presentation_region.width", "x + width must not exceed 1")
        if y + height > 1:
            report("layout.presentation_region.height", "y + height must not exceed 1")
        presentation_region = QuotationRegion(x=x, y=y, width=width, height=height)
    else:
        presentation_region = None

    fonts_data = _mapping(layout.get("fonts", {}), "layout.fonts", report)
    _known_fields(fonts_data, {"default", "available"}, "layout.fonts", report)
    default_value = fonts_data.get("default")
    default_fonts: tuple[str, ...] | None = None
    if not isinstance(default_value, list) or not default_value:
        report("layout.fonts.default", "is required and must be a nonempty sequence of font identifiers")
    else:
        valid_default_fonts: list[str] = []
        seen_default_fonts: set[str] = set()
        for index, identifier in enumerate(default_value):
            field = f"layout.fonts.default[{index}]"
            if not isinstance(identifier, str) or not identifier:
                report(field, "must be a nonempty font identifier")
            elif identifier in seen_default_fonts:
                report(field, f"duplicates font identifier {identifier!r}")
            else:
                valid_default_fonts.append(identifier)
                seen_default_fonts.add(identifier)
        default_fonts = tuple(valid_default_fonts)

    available_data: dict[str, object] = {}
    if "available" in fonts_data:
        available_data = _mapping(fonts_data["available"], "layout.fonts.available", report)

    font_registry: dict[str, FontResource] = {}
    package_root = files("refrain")
    for identifier, resource_parts in _BUNDLED_FONT_FILES.items():
        resource = package_root.joinpath(*resource_parts)
        if _load_font(resource, "layout.fonts", report):
            font_registry[identifier] = FontResource(identifier=identifier, path=resource, bundled=True)

    for identifier, path_value in available_data.items():
        field = f"layout.fonts.available.{identifier}"
        if not identifier:
            report("layout.fonts.available", "font identifiers must be nonempty strings")
            continue
        if identifier in _BUNDLED_FONT_FILES:
            report(field, f"identifier {identifier!r} is reserved for a bundled font")
            continue
        if not isinstance(path_value, str) or not path_value:
            report(field, "must be a nonempty font file path")
            continue
        font_path = Path(path_value)
        if not font_path.is_absolute():
            font_path = file.parent / font_path
        if _load_font(font_path, field, report):
            font_registry[identifier] = FontResource(identifier=identifier, path=font_path, bundled=False)

    if default_fonts is not None:
        for index, identifier in enumerate(default_fonts):
            if identifier not in font_registry:
                report(
                    f"layout.fonts.default[{index}]",
                    f"font identifier {identifier!r} is not present in the effective font registry",
                )

    text_data = _mapping(layout.get("text", {}), "layout.text", report)
    _known_fields(text_data, {"min_font_size", "max_font_size"}, "layout.text", report)
    sizes: dict[str, int] = {}
    for field in ("min_font_size", "max_font_size"):
        value = text_data.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            report(f"layout.text.{field}", "is required and must be a positive integer")
        else:
            sizes[field] = value
    if len(sizes) == 2 and sizes["max_font_size"] < sizes["min_font_size"]:
        report("layout.text.max_font_size", "must be greater than or equal to min_font_size")

    if diagnostics:
        raise ApplicationConfigurationError(tuple(diagnostics))

    assert timezone is not None
    assert day_start is not None
    assert content_directory is not None
    assert reveal is not None
    assert presentation_region is not None
    assert default_fonts is not None
    return ApplicationConfiguration(
        file=file,
        timezone=timezone,
        day_start=day_start,
        content_directory=content_directory,
        reveal=reveal,
        presentation_region=presentation_region,
        fonts=MappingProxyType(font_registry),
        default_fonts=default_fonts,
        min_font_size=sizes["min_font_size"],
        max_font_size=sizes["max_font_size"],
    )

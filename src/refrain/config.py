"""Load and validate Refrain application configuration."""

from __future__ import annotations

import ipaddress
import logging
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

_TOP_LEVEL_FIELDS = {"general", "content", "reveal", "display", "layout"}
_DISPLAY_BACKENDS = {"window", "waveshare-13in3-e", "image-server"}
_HOSTNAME_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\Z")
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
_LOGGER = logging.getLogger(__name__)
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
    severity: int = logging.ERROR

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
class PresentationRegion:
    """Normalized rectangle reserved for a literary composition."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class ApplicationConfiguration:
    """Validated, hardware-independent application configuration."""

    file: Path
    display_backend: str
    timezone: ZoneInfo
    day_start: time
    content_directory: Path
    reveal: RevealSchedule
    presentation_region: PresentationRegion
    fonts: Mapping[str, FontResource]
    default_fonts: tuple[str, ...]
    min_font_size: int
    max_font_size: int
    image_server_host: str = "127.0.0.1"
    image_server_port: int = 8080


def _known_fields(value: dict[str, object], allowed: set[str], field: str, report: Callable[..., None]) -> None:
    for key in sorted(value.keys() - allowed):
        report(
            f"{field}.{key}" if field else key,
            "is not a supported configuration field; it is ignored",
            logging.WARNING,
        )


def _mapping(value: object, field: str, report: Callable[..., None]) -> dict[str, object]:
    if not isinstance(value, dict):
        report(field, "must be a mapping; the value is ignored")
        return {}
    return value


def _parse_time(value: object, field: str, report: Callable[..., None], *, fallback: str | None = None) -> time | None:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        message = "must be a valid HH:MM local time"
        if fallback is not None:
            message += f"; using {fallback}"
        report(field, message)
        return None
    return time.fromisoformat(value)


def _valid_image_server_host(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        hostname = value[:-1] if value.endswith(".") else value
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        labels = ascii_hostname.split(".")
        return 0 < len(ascii_hostname) <= 253 and all(
            0 < len(label) <= 63 and _HOSTNAME_LABEL.fullmatch(label) for label in labels
        )


def _load_font(path: Union[Path, Traversable], field: str, report: Callable[[str, str], None]) -> bool:
    try:
        with path.open("rb") as font_file:
            ImageFont.truetype(font_file, size=12)
    except Exception as error:
        report(field, f"is excluded; it must be an existing, readable font supported by Pillow: {error}")
        return False
    return True


def load_application_config(config_file: Union[str, Path]) -> ApplicationConfiguration:
    """Load configuration, applying documented defaults and logging recoverable problems."""
    file = Path(config_file).absolute()
    diagnostics: list[ConfigurationDiagnostic] = []
    fatal_diagnostics: list[ConfigurationDiagnostic] = []
    defaults_used: list[str] = []

    def report(field: str, message: str, severity: int = logging.WARNING) -> None:
        diagnostic = ConfigurationDiagnostic(file=file, field=field, message=message, severity=severity)
        diagnostics.append(diagnostic)
        if severity >= logging.ERROR:
            fatal_diagnostics.append(diagnostic)

    def use_default(field: str, value: str) -> None:
        defaults_used.append(f"{field}={value}")

    def finish_diagnostics() -> None:
        for diagnostic in diagnostics:
            if diagnostic.severity >= logging.WARNING:
                _LOGGER.log(diagnostic.severity, "%s", diagnostic)
        if defaults_used:
            _LOGGER.info("%s: using documented defaults for optional fields: %s", file, ", ".join(defaults_used))

    try:
        contents = file.read_text(encoding="utf-8")
        data = load_yaml(contents)
    except (OSError, UnicodeError) as error:
        report("$", f"cannot read UTF-8 YAML file: {error}", logging.ERROR)
        finish_diagnostics()
        raise ApplicationConfigurationError(tuple(fatal_diagnostics)) from error
    except yaml.YAMLError as error:
        location = yaml_error_location(error)
        prefix = f"{location}: " if location else ""
        report("$", f"invalid or unsupported YAML: {prefix}{error}", logging.ERROR)
        finish_diagnostics()
        raise ApplicationConfigurationError(tuple(fatal_diagnostics)) from error

    if not isinstance(data, dict):
        report("$", "must contain one top-level mapping", logging.ERROR)
        finish_diagnostics()
        raise ApplicationConfigurationError(tuple(fatal_diagnostics))
    _known_fields(data, _TOP_LEVEL_FIELDS, "", report)

    display = _mapping(data.get("display", {}), "display", report)
    _known_fields(display, {"backend", "image-server"}, "display", report)
    display_backend = display.get("backend")
    if not isinstance(display_backend, str) or display_backend not in _DISPLAY_BACKENDS:
        if display_backend is None:
            report(
                "display.backend",
                "is required and must be one of: 'window', 'waveshare-13in3-e', 'image-server'",
                logging.ERROR,
            )
        else:
            report(
                "display.backend",
                "must be one of the supported backends: 'window', 'waveshare-13in3-e', 'image-server'",
                logging.ERROR,
            )
        display_backend = None
    image_server_host = "127.0.0.1"
    image_server_port = 8080
    if "image-server" not in display:
        use_default("display.image-server.host", repr(image_server_host))
        use_default("display.image-server.port", str(image_server_port))
    else:
        image_server_data = _mapping(display["image-server"], "display.image-server", report)
        _known_fields(image_server_data, {"host", "port"}, "display.image-server", report)
        host_value = image_server_data.get("host")
        if "host" not in image_server_data:
            use_default("display.image-server.host", repr(image_server_host))
        if _valid_image_server_host(host_value):
            image_server_host = host_value
        elif "host" in image_server_data:
            report(
                "display.image-server.host",
                "must be a nonempty local bind address or hostname; using the documented default '127.0.0.1'",
            )
        host_value = image_server_host
        port_value = image_server_data.get("port")
        if "port" not in image_server_data:
            use_default("display.image-server.port", str(image_server_port))
        if isinstance(port_value, bool) or not isinstance(port_value, int) or not 1 <= port_value <= 65535:
            if "port" in image_server_data:
                report(
                    "display.image-server.port",
                    "must be an integer between 1 and 65535; using the documented default 8080",
                )
        else:
            image_server_port = port_value

    general = _mapping(data.get("general", {}), "general", report)
    _known_fields(general, {"timezone", "day_start"}, "general", report)
    timezone_value = general.get("timezone")
    timezone: ZoneInfo | None = None
    if not isinstance(timezone_value, str) or not timezone_value:
        report("general.timezone", "is required and must be a valid IANA timezone identifier", logging.ERROR)
    elif timezone_value in _TIMEZONE_ABBREVIATIONS:
        report("general.timezone", "must be an IANA timezone identifier, not a timezone abbreviation", logging.ERROR)
    elif timezone_value in _NON_IANA_TIMEZONE_KEYS:
        report("general.timezone", "is not a portable IANA timezone identifier", logging.ERROR)
    elif timezone_value not in available_timezones():
        report("general.timezone", "is not a recognized IANA timezone identifier", logging.ERROR)
    else:
        try:
            timezone = ZoneInfo(timezone_value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            report("general.timezone", f"is not a valid IANA timezone identifier: {error}", logging.ERROR)

    if "day_start" not in general:
        use_default("general.day_start", "'06:00'")
    day_start = _parse_time(
        general.get("day_start", "06:00"),
        "general.day_start",
        report,
        fallback="the documented default '06:00'",
    )
    if day_start is None:
        day_start = time(6)

    content = _mapping(data.get("content", {}), "content", report)
    _known_fields(content, {"directory"}, "content", report)
    directory_value = content.get("directory", "content")
    if "directory" not in content:
        use_default("content.directory", "'content'")
    if not isinstance(directory_value, str) or not directory_value:
        report("content.directory", "must be a nonempty path string; using the documented default 'content'")
        directory_value = "content"
    content_directory = Path(directory_value)
    if not content_directory.is_absolute():
        content_directory = file.parent / content_directory

    reveal_data = _mapping(data.get("reveal", {}), "reveal", report)
    _known_fields(reveal_data, {"quotation", "source", "attribution"}, "reveal", report)
    quotation_default = day_start
    if "quotation" not in reveal_data:
        use_default("reveal.quotation", f"display-day start ({quotation_default:%H:%M})")
    quotation_fallback = f"the documented display-day start default {day_start:%H:%M}"
    quotation_time = _parse_time(
        reveal_data.get("quotation", quotation_default.strftime("%H:%M")),
        "reveal.quotation",
        report,
        fallback=quotation_fallback,
    )
    if quotation_time is None:
        quotation_time = day_start
    elif quotation_time != day_start:
        report("reveal.quotation", f"must coincide with general.day_start; using {quotation_fallback}")
        quotation_time = day_start

    reveal_times: dict[str, time] = {}
    for field, default in (("source", "12:00"), ("attribution", "18:00")):
        config_field = f"reveal.{field}"
        if field not in reveal_data:
            use_default(config_field, repr(default))
        parsed = _parse_time(
            reveal_data.get(field, default),
            config_field,
            report,
            fallback=f"the documented default {default!r}",
        )
        if parsed is None:
            parsed = time.fromisoformat(default)
        if parsed < day_start:
            if field in reveal_data:
                report(
                    config_field,
                    f"must not precede general.day_start; using the documented default {default!r}",
                )
                parsed = time.fromisoformat(default)
            if parsed < day_start:
                report(
                    config_field,
                    f"the documented default {default!r} precedes general.day_start; supply a valid reveal time",
                    logging.ERROR,
                )
        reveal_times[field] = parsed
    reveal = RevealSchedule(quotation_time, reveal_times["source"], reveal_times["attribution"])

    layout = _mapping(data.get("layout", {}), "layout", report)
    _known_fields(layout, {"presentation_region", "fonts", "text"}, "layout", report)
    region_data = _mapping(layout.get("presentation_region", {}), "layout.presentation_region", report)
    _known_fields(region_data, {"x", "y", "width", "height"}, "layout.presentation_region", report)
    region_values: dict[str, float] = {}
    for field in ("x", "y", "width", "height"):
        value = region_data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            report(f"layout.presentation_region.{field}", "is required and must be a finite number", logging.ERROR)
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
            report("layout.presentation_region.x", "must satisfy 0 <= x < 1", logging.ERROR)
        if not 0 <= y < 1:
            report("layout.presentation_region.y", "must satisfy 0 <= y < 1", logging.ERROR)
        if not 0 < width <= 1:
            report("layout.presentation_region.width", "must satisfy 0 < width <= 1", logging.ERROR)
        if not 0 < height <= 1:
            report("layout.presentation_region.height", "must satisfy 0 < height <= 1", logging.ERROR)
        if x + width > 1:
            report("layout.presentation_region.width", "x + width must not exceed 1", logging.ERROR)
        if y + height > 1:
            report("layout.presentation_region.height", "y + height must not exceed 1", logging.ERROR)
        presentation_region = PresentationRegion(x=x, y=y, width=width, height=height)
    else:
        presentation_region = None

    fonts_data = _mapping(layout.get("fonts", {}), "layout.fonts", report)
    _known_fields(fonts_data, {"default", "available"}, "layout.fonts", report)
    default_value = fonts_data.get("default")
    default_fonts: tuple[str, ...] = ()
    if not isinstance(default_value, list) or not default_value:
        report(
            "layout.fonts.default",
            "is required and must be a nonempty sequence of font identifiers",
            logging.ERROR,
        )

    available_data: dict[str, object] = {}
    if "available" in fonts_data:
        available_data = _mapping(fonts_data["available"], "layout.fonts.available", report)
    else:
        use_default("layout.fonts.available", "an empty mapping")

    font_registry: dict[str, FontResource] = {}
    package_root = files("refrain")
    for identifier, resource_parts in _BUNDLED_FONT_FILES.items():
        resource = package_root.joinpath(*resource_parts)
        if _load_font(resource, f"layout.fonts.bundled.{identifier}", report):
            font_registry[identifier] = FontResource(identifier=identifier, path=resource, bundled=True)

    for identifier, path_value in available_data.items():
        field = f"layout.fonts.available.{identifier}"
        if not identifier:
            report("layout.fonts.available", "font identifiers must be nonempty strings; this registration is ignored")
            continue
        if identifier in _BUNDLED_FONT_FILES:
            report(field, f"identifier {identifier!r} is reserved for a bundled font; this registration is ignored")
            continue
        if not isinstance(path_value, str) or not path_value:
            report(field, "must be a nonempty font file path; this registration is excluded")
            continue
        font_path = Path(path_value)
        if not font_path.is_absolute():
            font_path = file.parent / font_path
        if _load_font(font_path, field, report):
            font_registry[identifier] = FontResource(identifier=identifier, path=font_path, bundled=False)

    if isinstance(default_value, list):
        effective_default_fonts: list[str] = []
        seen_default_fonts: set[str] = set()
        for index, identifier in enumerate(default_value):
            field = f"layout.fonts.default[{index}]"
            if not isinstance(identifier, str) or not identifier:
                report(field, "must be a nonempty font identifier; it is excluded")
            elif identifier in seen_default_fonts:
                report(field, f"duplicates font identifier {identifier!r}; the duplicate is ignored")
            elif identifier not in font_registry:
                report(field, f"font identifier {identifier!r} is unavailable; it is excluded")
            else:
                effective_default_fonts.append(identifier)
            if isinstance(identifier, str):
                seen_default_fonts.add(identifier)
        default_fonts = tuple(effective_default_fonts)

    text_data = _mapping(layout.get("text", {}), "layout.text", report)
    _known_fields(text_data, {"min_font_size", "max_font_size"}, "layout.text", report)
    sizes: dict[str, int] = {}
    for field in ("min_font_size", "max_font_size"):
        value = text_data.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            report(f"layout.text.{field}", "is required and must be a positive integer", logging.ERROR)
        else:
            sizes[field] = value
    if len(sizes) == 2 and sizes["max_font_size"] < sizes["min_font_size"]:
        report("layout.text.max_font_size", "must be greater than or equal to min_font_size", logging.ERROR)

    finish_diagnostics()
    if fatal_diagnostics:
        raise ApplicationConfigurationError(tuple(fatal_diagnostics))

    assert timezone is not None
    assert presentation_region is not None
    assert display_backend is not None
    return ApplicationConfiguration(
        file=file,
        display_backend=display_backend,
        timezone=timezone,
        day_start=day_start,
        content_directory=content_directory,
        reveal=reveal,
        presentation_region=presentation_region,
        fonts=MappingProxyType(font_registry),
        default_fonts=default_fonts,
        min_font_size=sizes["min_font_size"],
        max_font_size=sizes["max_font_size"],
        image_server_host=image_server_host,
        image_server_port=image_server_port,
    )

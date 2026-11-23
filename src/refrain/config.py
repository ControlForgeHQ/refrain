"""Load and validate Refrain application configuration."""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass, field
from datetime import time
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Union

import yaml
from PIL import Image

from ._yaml import load_yaml, yaml_error_location
from .assets import parse_font_faces, valid_identifier
from .geometry import (
    DEFAULT_PRESENTATION_INSETS,
    SUPPORTED_PRESENTATION_ASPECTS,
    PresentationGeometryError,
    PresentationInsets,
    ResolvedOutputSpecification,
    design_canvas_for_aspect,
    validate_presentation_insets,
    validate_requested_size,
)

_TOP_LEVEL_FIELDS = {
    "destinations",
    "image-server",
    "storage",
    "scheduling",
    "presentation",
    "palette",
    "fonts",
    "text",
    "backgrounds",
    "decorations",
}
_DISPLAY_BACKENDS = {"window", "waveshare-13in3-e", "image-server", "publish"}
_MAX_DESTINATION_IDENTIFIER_LENGTH = 256
_DESTINATION_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_WINDOWS_RESERVED_DESTINATION_IDS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_HOSTNAME_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\Z")
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_LOGGER = logging.getLogger(__name__)
_BUILTIN_PALETTE = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "yellow": "#FFFF00",
    "blue": "#0000FF",
    "green": "#00FF00",
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
    """A validated font bundle whose regular face preserves initial rendering behavior."""

    identifier: str
    path: Union[Path, Traversable]
    bundled: bool
    faces: Mapping[str, Union[Path, Traversable]] = field(default_factory=lambda: MappingProxyType({}))
    font_faces: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class BackgroundResource:
    """A validated standalone PNG or packaged background composition."""

    identifier: str
    path: Union[Path, Traversable, None]
    bundled: bool
    layers: tuple[BackgroundLayerResource, ...] = ()
    text_color: tuple[str, ...] | None = None
    decoration_color: tuple[str, ...] | None = None
    manifest: Union[Path, Traversable, None] = field(default=None, compare=False)


@dataclass(frozen=True)
class NineSliceParameters:
    """Validated source-pixel boundaries and edge transformation modes."""

    left: int
    right: int
    top: int
    bottom: int
    horizontal: str = "stretch"
    vertical: str = "stretch"


@dataclass(frozen=True)
class LayerAnchor:
    """Validated horizontal and vertical alignment for a visual layer."""

    horizontal: str
    vertical: str


@dataclass(frozen=True)
class CompositionLayerResource:
    """A validated image layer with shared raster-composition behavior."""

    image: Union[Path, Traversable]
    method: str
    nine_slice: NineSliceParameters | None = None
    scale: str | None = None
    anchor: LayerAnchor | None = None


@dataclass(frozen=True)
class BackgroundLayerResource(CompositionLayerResource):
    """A validated image layer in a background manifest."""


@dataclass(frozen=True)
class DecorationLayerResource(CompositionLayerResource):
    """A validated image layer in a decoration manifest."""

    condition: str = "always"
    tintable: bool = True


@dataclass(frozen=True)
class DecorationResource:
    """A validated bundled or discovered decoration and its ordered layers."""

    identifier: str
    layers: tuple[DecorationLayerResource, ...]
    bundled: bool
    presentation_insets: PresentationInsets | None = None
    font: str | None = None
    background: str | None = None
    font_faces: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    text_color: tuple[str, ...] | None = None
    tintable: bool = True
    decoration_color: tuple[str, ...] | None = None
    qr_ready: bool = True
    qr_positioning: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    manifest: Union[Path, Traversable, None] = field(default=None, compare=False)


@dataclass(frozen=True)
class RevealSchedule:
    """Validated global reveal times in the operating-system local timezone."""

    source: time
    attribution: time


@dataclass(frozen=True)
class DestinationPresentation:
    """Destination-local preferences that define a compatible preparation group."""

    background: str | None = None
    decoration: str | None = None
    font: str | None = None
    text_color: tuple[str, ...] | None = None
    decoration_color: tuple[str, ...] | None = None
    qr_enabled: bool | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether this declaration leaves all normal presentation preferences intact."""
        return all(
            value is None
            for value in (
                self.background,
                self.decoration,
                self.font,
                self.text_color,
                self.decoration_color,
                self.qr_enabled,
            )
        )


@dataclass(frozen=True)
class PreparedImageVariantKey:
    """Identify a raster variant within its destination-independent preparation group."""

    output_specification: ResolvedOutputSpecification
    presentation: DestinationPresentation


@dataclass(frozen=True)
class DisplayOutputConfiguration:
    """Validated identity and output specification for one display destination."""

    identifier: str
    output_specification: ResolvedOutputSpecification
    presentation: DestinationPresentation = field(default_factory=DestinationPresentation)
    audience: str = field(kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.audience, str) or self.audience not in {"public", "private"}:
            raise ValueError("audience must be 'public' or 'private'")

    @property
    def prepared_image_key(self) -> ResolvedOutputSpecification | PreparedImageVariantKey:
        """Return the shared raster key, including destination presentation requirements when set."""
        if self.presentation.is_empty:
            return self.output_specification
        return PreparedImageVariantKey(self.output_specification, self.presentation)


@dataclass(frozen=True)
class DisplayBackendConfiguration:
    """Validated settings for one configured built-in display backend."""

    type: str
    host: str = "127.0.0.1"
    port: int = 8080
    outputs: tuple[DisplayOutputConfiguration, ...] = ()
    service_enabled: bool = True


@dataclass(frozen=True)
class StorageConfiguration:
    """Optional configuration-relative runtime storage paths."""

    state: Path | None = None
    history: Path | None = None
    artifacts: Path | None = None
    publish: Path | None = None


@dataclass(frozen=True)
class ApplicationConfiguration:
    """Validated, hardware-independent application configuration."""

    file: Path
    display_backends: tuple[DisplayBackendConfiguration, ...]
    day_start: time
    content_directory: Path
    reveal: RevealSchedule
    presentation_insets: PresentationInsets
    fonts: Mapping[str, FontResource]
    default_fonts: tuple[str, ...]
    min_font_size: int
    max_font_size: int
    storage: StorageConfiguration = field(default_factory=StorageConfiguration)
    information_view_duration: int = 60
    qr_enabled: bool = True
    backgrounds: Mapping[str, BackgroundResource] = field(default_factory=lambda: MappingProxyType({}))
    default_backgrounds: tuple[str, ...] = ("none",)
    decorations: Mapping[str, DecorationResource] = field(default_factory=lambda: MappingProxyType({}))
    default_decorations: tuple[str, ...] = ("none",)
    font_faces: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    palette: Mapping[str, str] = field(default_factory=lambda: MappingProxyType(_BUILTIN_PALETTE))
    default_text_colors: tuple[str, ...] = ("black",)
    default_decoration_colors: tuple[str, ...] = ("black",)
    font_pools: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    background_pools: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    decoration_pools: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    text_color_pools: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    decoration_color_pools: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def required_output_specifications(self) -> tuple[ResolvedOutputSpecification, ...]:
        """Return the unique output specifications required by configured destinations."""
        return tuple(
            sorted(
                {output.output_specification for backend in self.display_backends for output in backend.outputs},
                key=lambda specification: (specification.aspect_ratio, specification.requested_output_size),
            )
        )

    @property
    def required_prepared_image_keys(self) -> tuple[ResolvedOutputSpecification | PreparedImageVariantKey, ...]:
        """Return the unique destination-compatible raster variants required by the runtime."""
        keys = {output.prepared_image_key for backend in self.display_backends for output in backend.outputs}

        def sort_key(key: ResolvedOutputSpecification | PreparedImageVariantKey) -> tuple[object, ...]:
            specification = key.output_specification if isinstance(key, PreparedImageVariantKey) else key
            return (
                specification.aspect_ratio,
                specification.requested_output_size,
                repr(key.presentation) if isinstance(key, PreparedImageVariantKey) else "",
            )

        return tuple(sorted(keys, key=sort_key))


def _known_fields(
    value: dict[str, object],
    allowed: set[str],
    field: str,
    report: Callable[..., None],
    *,
    strict: bool = False,
) -> None:
    unknown_keys = value.keys() - allowed
    for key in sorted(unknown_keys, key=lambda item: (type(item).__name__, repr(item))):
        key_field = (
            f"{field}.{key}"
            if isinstance(key, str) and field
            else (key if isinstance(key, str) else f"{field}[{key!r}]")
        )
        report(
            key_field,
            (
                "is not a supported configuration field"
                if strict
                else "is not a supported configuration field; it is ignored"
            ),
            logging.ERROR if strict else logging.WARNING,
        )


def _mapping(value: object, field: str, report: Callable[..., None]) -> dict[str, object]:
    if not isinstance(value, dict):
        report(field, "must be a mapping; the value is ignored")
        return {}
    return value


def _parse_requested_output_size(value: object, field: str, report: Callable[..., None]) -> tuple[int, int] | None:
    try:
        return validate_requested_size(value)
    except PresentationGeometryError as error:
        report(field, str(error), logging.ERROR)
        return None


def _resolve_output_specification(
    value: dict[str, object],
    field: str,
    report: Callable[..., None],
    *,
    default_aspect: str,
    default_size: tuple[int, int],
) -> ResolvedOutputSpecification:
    has_aspect = "aspect_ratio" in value
    has_size = "resolution" in value
    if has_aspect != has_size:
        report(
            field,
            "aspect_ratio and resolution must either both be supplied or both be omitted",
            logging.ERROR,
        )

    aspect_ratio = value.get("aspect_ratio", default_aspect)
    if not isinstance(aspect_ratio, str) or aspect_ratio not in SUPPORTED_PRESENTATION_ASPECTS:
        report(
            f"{field}.aspect_ratio",
            "must be one of the supported presentation aspects: 4:3, 5:3, 16:9, or 16:10",
            logging.ERROR,
        )
        aspect_ratio = default_aspect

    requested_size = default_size
    if has_size:
        parsed_size = _parse_requested_output_size(value["resolution"], f"{field}.resolution", report)
        if parsed_size is not None:
            requested_size = parsed_size
    return ResolvedOutputSpecification(aspect_ratio, requested_size)


def _parse_presentation_insets(
    value: object,
    field: str,
    report: Callable[..., None],
    severity: int = logging.ERROR,
) -> PresentationInsets | None:
    if not isinstance(value, dict):
        report(field, "must be a mapping", severity)
        return None
    _known_fields(value, {"left", "right", "top", "bottom"}, field, report)
    values: dict[str, int] = {}
    for edge in ("left", "right", "top", "bottom"):
        edge_value = value.get(edge)
        if type(edge_value) is not int or edge_value < 0:
            report(
                f"{field}.{edge}",
                "is required and must be a nonnegative integer design-canvas pixel value",
                severity,
            )
        else:
            values[edge] = edge_value
    if len(values) != 4:
        return None
    return PresentationInsets(**values)


def _parse_decoration_insets(
    value: object,
    field: str,
    report: Callable[..., None],
    severity: int,
    aspect_ratios: tuple[str, ...],
) -> PresentationInsets | None:
    insets = _parse_presentation_insets(value, field, report, severity)
    if insets is None:
        return None
    for aspect_ratio in aspect_ratios:
        design_canvas_size, _ = design_canvas_for_aspect(aspect_ratio)
        try:
            validate_presentation_insets(insets, design_canvas_size)
        except PresentationGeometryError as error:
            report(field, f"is invalid for the {aspect_ratio} design canvas: {error}", severity)
            return None
    return insets


def _parse_time(value: object, field: str, report: Callable[..., None], *, fallback: str | None = None) -> time | None:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        message = "must be a valid HH:MM local time"
        if fallback is not None:
            message += f"; using {fallback}"
        report(field, message)
        return None
    return time.fromisoformat(value)


def _configured_pools(
    section: dict[str, object],
    field: str,
    allowed_fields: set[str],
    report: Callable[..., None],
) -> dict[str, object]:
    _known_fields(section, allowed_fields | {"pools"}, field, report)
    if "pools" not in section:
        return {}
    return _mapping(section["pools"], f"{field}.pools", report)


def _resolve_configured_pools(
    section: dict[str, object],
    field: str,
    available: set[str],
    builtin: tuple[str, ...],
    report: Callable[..., None],
    *,
    default_fallback: tuple[str, ...] | None = None,
    default_required: bool = False,
    default_label: str = "resource identifiers",
    identifier_label: str = "resource",
    allow_none: bool = False,
    warn_duplicates: bool = False,
) -> tuple[Mapping[str, tuple[str, ...]], tuple[str, ...]]:
    definitions: dict[str, object] = {}
    for name, value in section.items():
        location = f"{field}.{name}" if isinstance(name, str) else f"{field}[{name!r}]"
        if not valid_identifier(name):
            report(location, "must be a valid ASCII pool name; the pool is ignored")
        elif name == "builtin":
            report(location, "is reserved for the built-in resource pool; the definition is ignored")
        else:
            definitions[name] = value

    if "default" not in definitions:
        if default_required:
            report(
                f"{field}.default",
                f"is required and must be a nonempty sequence of {default_label}",
                logging.ERROR,
            )
            definitions["default"] = []
        else:
            definitions["default"] = list(default_fallback or ())
    elif not isinstance(definitions["default"], list) or not definitions["default"]:
        severity = logging.ERROR if default_required else logging.WARNING
        report(
            f"{field}.default",
            (
                f"is required and must be a nonempty sequence of {default_label}"
                if default_required
                else f"must be a nonempty sequence of {default_label}"
            ),
            severity,
        )
        definitions["default"] = []

    normalized: dict[str, list[object]] = {}
    for name, value in definitions.items():
        location = f"{field}.{name}"
        if not isinstance(value, list):
            report(location, "must be a sequence of resource identifiers; the pool is empty")
            normalized[name] = []
        else:
            normalized[name] = value
    normalized["builtin"] = list(builtin)

    resolved: dict[str, tuple[str, ...]] = {"builtin": tuple(builtin)}
    for root in normalized:
        if root == "builtin" or root in resolved:
            continue
        ordered: list[str] = []
        seen: set[str] = set()

        def expand(name: str, active: tuple[str, ...]) -> None:
            for index, member in enumerate(normalized[name]):
                location = f"{field}.{name}[{index}]"
                if not isinstance(member, str):
                    report(location, f"must be a valid {identifier_label} identifier; it is excluded")
                    continue
                if member.startswith("@"):
                    reference = member[1:]
                    if not valid_identifier(reference):
                        report(location, f"pool reference {member!r} is malformed; it is excluded")
                        continue
                    if reference in active:
                        continue
                    if reference not in normalized:
                        report(location, f"pool reference {member!r} is unknown; it is excluded")
                        continue
                    expand(reference, (*active, reference))
                    continue
                if not valid_identifier(member):
                    report(location, f"must be a valid {identifier_label} identifier; it is excluded")
                    continue
                if member == "none" and allow_none:
                    candidate = member
                elif member in available:
                    candidate = member
                else:
                    report(location, f"{identifier_label} identifier {member!r} is unavailable; it is excluded")
                    continue
                if candidate in seen:
                    if warn_duplicates:
                        report(
                            location,
                            f"duplicates {identifier_label} identifier {candidate!r}; the duplicate is ignored",
                        )
                    continue
                seen.add(candidate)
                ordered.append(candidate)

        expand(root, (root,))
        resolved[root] = tuple(ordered)

    return MappingProxyType(resolved), resolved["default"]


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


def _parse_palette(data: dict[str, object], report: Callable[..., None]) -> dict[str, str]:
    palette = dict(_BUILTIN_PALETTE)
    if "palette" not in data:
        return palette
    for identifier, value in _mapping(data["palette"], "palette", report).items():
        field = f"palette.{identifier}" if isinstance(identifier, str) else f"palette[{identifier!r}]"
        if not valid_identifier(identifier):
            report(field, "must be a valid palette identifier; the colour is ignored")
        elif not isinstance(value, str) or not _HEX_COLOR.fullmatch(value):
            report(field, "must be a quoted six-digit #RRGGBB colour; the colour is ignored")
        else:
            palette[identifier] = value
    return palette


def _parse_storage(
    data: dict[str, object],
    file: Path,
    report: Callable[..., None],
) -> tuple[Path, StorageConfiguration]:
    storage_data: dict[str, object] = {}
    if "storage" in data:
        if not isinstance(data["storage"], dict):
            report("storage", "must be a mapping", logging.ERROR)
        else:
            storage_data = data["storage"]
            _known_fields(storage_data, {"content", "state", "history", "artifacts", "publish"}, "storage", report)

    content_value = storage_data.get("content", "content")
    if not isinstance(content_value, str) or not content_value:
        report("storage.content", "must be a nonempty path string; using the documented default 'content'")
        content_value = "content"
    content_directory = Path(content_value)
    if not content_directory.is_absolute():
        content_directory = file.parent / content_directory

    storage_values: dict[str, Path] = {}
    for storage_field in ("state", "history", "artifacts", "publish"):
        if storage_field not in storage_data:
            continue
        value = storage_data[storage_field]
        if not isinstance(value, str) or not value:
            report(f"storage.{storage_field}", "must be a nonempty path string", logging.ERROR)
            continue
        storage_path = Path(value)
        if not storage_path.is_absolute():
            storage_path = file.parent / storage_path
        storage_values[storage_field] = storage_path
    return content_directory, StorageConfiguration(**storage_values)


def _parse_scheduling(
    data: dict[str, object],
    report: Callable[..., None],
) -> tuple[time, RevealSchedule]:
    scheduling = _mapping(data.get("scheduling", {}), "scheduling", report)
    _known_fields(scheduling, {"day_start", "reveal"}, "scheduling", report)
    day_start = _parse_time(
        scheduling.get("day_start", "05:00"),
        "scheduling.day_start",
        report,
        fallback="the documented default '05:00'",
    )
    if day_start is None:
        day_start = time(5)

    reveal_data = _mapping(scheduling.get("reveal", {}), "scheduling.reveal", report)
    _known_fields(reveal_data, {"source", "attribution"}, "scheduling.reveal", report)
    reveal_times: dict[str, time] = {}
    for name, default in (("source", "12:00"), ("attribution", "18:00")):
        config_field = f"scheduling.reveal.{name}"
        parsed = _parse_time(
            reveal_data.get(name, default),
            config_field,
            report,
            fallback=f"the documented default {default!r}",
        )
        if parsed is None:
            parsed = time.fromisoformat(default)
        if parsed < day_start:
            if name in reveal_data:
                report(
                    config_field,
                    f"must not precede scheduling.day_start; using the documented default {default!r}",
                )
                parsed = time.fromisoformat(default)
            if parsed < day_start:
                report(
                    config_field,
                    f"the documented default {default!r} precedes scheduling.day_start; supply a valid reveal time",
                    logging.ERROR,
                )
        reveal_times[name] = parsed
    return day_start, RevealSchedule(reveal_times["source"], reveal_times["attribution"])


def _parse_presentation(
    data: dict[str, object],
    report: Callable[..., None],
    aspect_ratios: tuple[str, ...],
) -> tuple[PresentationInsets, int, bool]:
    presentation = _mapping(data.get("presentation", {}), "presentation", report)
    _known_fields(presentation, {"insets", "information_view", "qr"}, "presentation", report)

    if "insets" not in presentation:
        insets = PresentationInsets(*DEFAULT_PRESENTATION_INSETS)
    else:
        insets = _parse_presentation_insets(presentation["insets"], "presentation.insets", report)
    if insets is None:
        insets = PresentationInsets(*DEFAULT_PRESENTATION_INSETS)
    for aspect_ratio in aspect_ratios:
        design_canvas_size, _ = design_canvas_for_aspect(aspect_ratio)
        try:
            validate_presentation_insets(insets, design_canvas_size)
        except PresentationGeometryError as error:
            report("presentation.insets", str(error), logging.ERROR)

    information_view = _mapping(presentation.get("information_view", {}), "presentation.information_view", report)
    _known_fields(information_view, {"duration"}, "presentation.information_view", report)
    duration = information_view.get("duration", 60)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 0 <= duration <= 300:
        report(
            "presentation.information_view.duration",
            "must be an integer between 0 and 300; using the documented default 60",
        )
        duration = 60

    qr = _mapping(presentation.get("qr", {}), "presentation.qr", report)
    _known_fields(qr, {"enabled"}, "presentation.qr", report)
    qr_enabled = qr.get("enabled", True)
    if "enabled" in qr and type(qr_enabled) is not bool:
        report("presentation.qr.enabled", "must be a YAML boolean; QR generation remains enabled", logging.WARNING)
        qr_enabled = True
    return insets, duration, qr_enabled


def _parse_destination_overrides(
    value: object,
    field: str,
    report: Callable[..., None],
) -> DestinationPresentation:
    if not isinstance(value, dict):
        report(field, "must be a mapping", logging.ERROR)
        return DestinationPresentation()

    _known_fields(
        value,
        {"background", "decoration", "font", "text_color", "decoration_color", "qr"},
        field,
        report,
        strict=True,
    )
    resolved: dict[str, object] = {}
    for name in ("background", "decoration", "qr"):
        if name not in value:
            continue
        override = value[name]
        if not isinstance(override, str) or override != "none":
            report(f"{field}.{name}", "must be the literal string 'none'", logging.ERROR)
        elif name == "qr":
            resolved["qr_enabled"] = False
        else:
            resolved[name] = override

    if "font" in value:
        font = value["font"]
        if not valid_identifier(font):
            report(f"{field}.font", "must be one registered font-bundle identifier", logging.ERROR)
        else:
            resolved["font"] = font
    for name in ("text_color", "decoration_color"):
        if name not in value:
            continue
        color = value[name]
        if valid_identifier(color):
            resolved[name] = (color,)
        else:
            report(f"{field}.{name}", "must be one effective palette identifier", logging.ERROR)

    return DestinationPresentation(**resolved)


def _validate_destination_override_resources(
    data: dict[str, object],
    fonts: Mapping[str, FontResource],
    palette: Mapping[str, str],
    report: Callable[..., None],
) -> None:
    destinations = data.get("destinations")
    if not isinstance(destinations, list):
        return
    for index, destination in enumerate(destinations):
        if not isinstance(destination, dict):
            continue
        overrides = destination.get("overrides")
        if not isinstance(overrides, dict):
            continue
        field = f"destinations[{index}].overrides"
        font = overrides.get("font")
        if valid_identifier(font) and font not in fonts:
            report(f"{field}.font", f"font bundle {font!r} is not registered", logging.ERROR)
        for name in ("text_color", "decoration_color"):
            color = overrides.get(name)
            if valid_identifier(color) and color not in palette:
                report(f"{field}.{name}", f"palette identifier {color!r} is not available", logging.ERROR)


def _parse_destinations(
    data: dict[str, object],
    report: Callable[..., None],
) -> tuple[DisplayBackendConfiguration, ...]:
    from .display.capabilities import DESTINATION_CAPACITIES

    image_server_enabled = "image-server" in data
    image_server_value = data.get("image-server", {})
    if image_server_value is None:
        image_server_value = {}
    image_server = _mapping(image_server_value, "image-server", report)
    _known_fields(image_server, {"host", "port"}, "image-server", report)
    image_server_host = "127.0.0.1"
    image_server_port = 8080
    if image_server_enabled:
        if "host" in image_server and _valid_image_server_host(image_server["host"]):
            image_server_host = image_server["host"]
        elif "host" in image_server:
            report(
                "image-server.host",
                "must be a nonempty local bind address or hostname; using the documented default '127.0.0.1'",
            )
        port_value = image_server.get("port", image_server_port)
        if isinstance(port_value, bool) or not isinstance(port_value, int) or not 1 <= port_value <= 65535:
            report("image-server.port", "must be an integer between 1 and 65535; using the documented default 8080")
        else:
            image_server_port = port_value

    configured_destinations = data.get("destinations")
    destination_groups: dict[str, list[DisplayOutputConfiguration]] = {}
    destination_counts: dict[str, int] = {}
    seen_destination_ids: set[str] = set()
    seen_publish_directory_ids: set[str] = set()
    if not isinstance(configured_destinations, list) or not configured_destinations:
        report("destinations", "is required and must be a nonempty sequence of destination mappings", logging.ERROR)
    else:
        for index, value in enumerate(configured_destinations):
            field = f"destinations[{index}]"
            if not isinstance(value, dict):
                report(field, "must be a destination mapping", logging.ERROR)
                continue
            _known_fields(value, {"id", "type", "aspect_ratio", "resolution", "overrides", "audience"}, field, report)
            audience = value.get("audience")
            if not isinstance(audience, str) or audience not in {"public", "private"}:
                report(f"{field}.audience", "is required and must be 'public' or 'private'", logging.ERROR)
                continue
            presentation = (
                _parse_destination_overrides(value["overrides"], f"{field}.overrides", report)
                if "overrides" in value
                else DestinationPresentation()
            )
            identifier = value.get("id")
            if (
                not isinstance(identifier, str)
                or not _DESTINATION_IDENTIFIER.fullmatch(identifier)
                or len(identifier) > _MAX_DESTINATION_IDENTIFIER_LENGTH
            ):
                report(
                    f"{field}.id",
                    "is required and must match [A-Za-z0-9][A-Za-z0-9_-]* and be at most 256 characters",
                    logging.ERROR,
                )
                continue
            if identifier in seen_destination_ids:
                report(f"{field}.id", f"duplicates destination ID {identifier!r}", logging.ERROR)
                continue
            seen_destination_ids.add(identifier)

            backend_type = value.get("type")
            if not isinstance(backend_type, str) or backend_type not in _DISPLAY_BACKENDS:
                report(
                    f"{field}.type",
                    "must be one of the supported backends: "
                    "'window', 'waveshare-13in3-e', 'image-server', 'publish'",
                    logging.ERROR,
                )
                continue
            if backend_type == "publish":
                if identifier.upper() in _WINDOWS_RESERVED_DESTINATION_IDS:
                    report(
                        f"{field}.id",
                        "must not be a Windows-reserved device name",
                        logging.ERROR,
                    )
                    continue
                directory_identifier = identifier.casefold()
                if directory_identifier in seen_publish_directory_ids:
                    report(
                        f"{field}.id",
                        f"conflicts with a case-insensitive publish destination directory named {identifier!r}",
                        logging.ERROR,
                    )
                    continue
                seen_publish_directory_ids.add(directory_identifier)
            destination_counts[backend_type] = destination_counts.get(backend_type, 0) + 1
            capacity = DESTINATION_CAPACITIES[backend_type]
            if capacity is not None and destination_counts[backend_type] > capacity:
                report(
                    f"{field}.type",
                    f"backend {backend_type!r} supports at most {capacity} destination(s)",
                    logging.ERROR,
                )
                continue

            if backend_type in {"window", "image-server"}:
                default_aspect, default_size = (
                    ("16:9", (1920, 1080)) if backend_type == "window" else ("16:10", (3840, 2400))
                )
                specification = _resolve_output_specification(
                    value,
                    field,
                    report,
                    default_aspect=default_aspect,
                    default_size=default_size,
                )
            elif backend_type == "publish":
                specification = _resolve_output_specification(
                    value,
                    field,
                    report,
                    default_aspect="16:10",
                    default_size=(3840, 2400),
                )
            else:
                for forbidden_field in ("aspect_ratio", "resolution"):
                    if forbidden_field in value:
                        report(
                            f"{field}.{forbidden_field}",
                            "is not valid for the fixed 4:3 @ 1600 × 1200 Waveshare output",
                            logging.ERROR,
                        )
                specification = ResolvedOutputSpecification("4:3", (1600, 1200))
            destination_groups.setdefault(backend_type, []).append(
                DisplayOutputConfiguration(identifier, specification, presentation, audience=audience)
            )

    return tuple(
        DisplayBackendConfiguration(
            backend_type,
            image_server_host,
            image_server_port,
            tuple(outputs),
            image_server_enabled,
        )
        for backend_type, outputs in destination_groups.items()
    )


def _parse_color_pools(
    section: dict[str, object],
    field: str,
    palette: Mapping[str, str],
    report: Callable[..., None],
) -> tuple[Mapping[str, tuple[str, ...]], tuple[str, ...]]:
    colors = _mapping(section.get("colors", {}), f"{field}.colors", report)
    pools = _configured_pools(colors, f"{field}.colors", set(), report)
    return _resolve_configured_pools(
        pools,
        f"{field}.colors.pools",
        set(palette),
        ("black",),
        report,
        default_fallback=("black",),
        default_label="palette identifiers",
        identifier_label="palette",
        warn_duplicates=True,
    )


def _load_font_resources(
    section: dict[str, object],
    file: Path,
    package_root: Traversable,
    report: Callable[..., None],
) -> tuple[dict[str, FontResource], Mapping[str, tuple[str, ...]], tuple[str, ...], Mapping[str, str]]:
    from .assets import discover_fonts

    pools = _configured_pools(section, "fonts", {"faces"}, report)
    registry = discover_fonts(
        package_root.joinpath("assets", "fonts"),
        file.parent / "assets" / "fonts",
        report,
    )
    faces = parse_font_faces(section["faces"], "fonts.faces", report) if "faces" in section else MappingProxyType({})
    resolved_pools, default = _resolve_configured_pools(
        pools,
        "fonts.pools",
        set(registry),
        tuple(sorted(identifier for identifier, resource in registry.items() if resource.bundled)),
        report,
        default_required=True,
        default_label="font identifiers",
        identifier_label="font",
        warn_duplicates=True,
    )
    return registry, resolved_pools, default, faces


def _load_background_resources(
    section: dict[str, object],
    file: Path,
    package_root: Traversable,
    report: Callable[..., None],
) -> tuple[dict[str, BackgroundResource], Mapping[str, tuple[str, ...]], tuple[str, ...]]:
    from .assets import discover_backgrounds

    pools = _configured_pools(section, "backgrounds", set(), report)
    registry = discover_backgrounds(
        package_root.joinpath("assets", "backgrounds"),
        file.parent / "assets" / "backgrounds",
        report,
    )
    resolved_pools, default = _resolve_configured_pools(
        pools,
        "backgrounds.pools",
        set(registry),
        tuple(sorted(identifier for identifier, resource in registry.items() if resource.bundled)),
        report,
        default_fallback=("none",),
        default_label="background identifiers",
        identifier_label="background",
        allow_none=True,
    )
    return registry, resolved_pools, default


def _load_decoration_resources(
    section: dict[str, object],
    file: Path,
    package_root: Traversable,
    fonts: Mapping[str, FontResource],
    backgrounds: Mapping[str, BackgroundResource],
    palette: Mapping[str, str],
    aspect_ratios: tuple[str, ...],
    report: Callable[..., None],
) -> tuple[
    dict[str, DecorationResource],
    Mapping[str, tuple[str, ...]],
    tuple[str, ...],
    Mapping[str, tuple[str, ...]],
    tuple[str, ...],
]:
    from .assets import discover_decorations

    pools = _configured_pools(section, "decorations", {"colors"}, report)
    registry = discover_decorations(
        package_root.joinpath("assets", "decorations"),
        file.parent / "assets" / "decorations",
        set(fonts),
        set(backgrounds),
        report,
        lambda value, field, reporter, severity=logging.ERROR: _parse_decoration_insets(
            value, field, reporter, severity, aspect_ratios
        ),
    )
    resolved_pools, default = _resolve_configured_pools(
        pools,
        "decorations.pools",
        set(registry),
        tuple(sorted(identifier for identifier, resource in registry.items() if resource.bundled)),
        report,
        default_fallback=("none",),
        default_label="decoration identifiers",
        identifier_label="decoration",
        allow_none=True,
    )
    color_pools, default_colors = _parse_color_pools(section, "decorations", palette, report)
    return registry, resolved_pools, default, color_pools, default_colors


def _load_text_settings(
    section: dict[str, object],
    palette: Mapping[str, str],
    report: Callable[..., None],
) -> tuple[Mapping[str, tuple[str, ...]], tuple[str, ...], int, int]:
    _known_fields(section, {"colors", "min_font_size", "max_font_size"}, "text", report)
    color_pools, default_colors = _parse_color_pools(section, "text", palette, report)
    bounds: dict[str, int] = {}
    for name, default in (("min_font_size", 56), ("max_font_size", 200)):
        value = section.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            report(f"text.{name}", "must be a positive integer", logging.ERROR)
            value = default
        bounds[name] = value
    if bounds["max_font_size"] < bounds["min_font_size"]:
        report("text.max_font_size", "must be greater than or equal to min_font_size", logging.ERROR)
    return color_pools, default_colors, bounds["min_font_size"], bounds["max_font_size"]


def load_background_image(resource: BackgroundResource) -> Image.Image:
    """Revalidate and return a fully decoded RGB/RGBA image owned by the caller.

    Unreadable resources raise their loading exception; unsupported images raise
    ``ValueError``. No image is cached, so regeneration checks the current resource.
    The decoded image is returned directly to avoid a second full-resolution copy.
    """
    if resource.path is None:
        raise ValueError("packaged background images are loaded from their layers")
    return _load_layer_image(resource.path, "background")


def load_decoration_layer_image(resource: DecorationLayerResource) -> Image.Image:
    """Revalidate and return a fully decoded RGB or RGBA layer owned by the caller."""
    return _load_layer_image(resource.image, "decoration")


def load_composition_layer_image(resource: CompositionLayerResource) -> Image.Image:
    """Revalidate and return a fully decoded RGB or RGBA composition layer."""
    category = "background" if isinstance(resource, BackgroundLayerResource) else "decoration"
    return _load_layer_image(resource.image, category)


def _load_layer_image(path: Union[Path, Traversable], category: str) -> Image.Image:
    with path.open("rb") as image_file:
        image = Image.open(image_file)
        try:
            if image.format != "PNG":
                raise ValueError(f"{category} must be a PNG image")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError(f"{category} must be a single-frame PNG image")
            if image.mode not in {"RGB", "RGBA"}:
                raise ValueError(f"{category} mode must be RGB or RGBA")
            image.load()
        except Exception:
            image.close()
            raise
        return image


def load_application_config(config_file: Union[str, Path]) -> ApplicationConfiguration:
    """Load configuration, applying documented defaults and logging recoverable problems."""
    file = Path(config_file).absolute()
    diagnostics: list[ConfigurationDiagnostic] = []
    fatal_diagnostics: list[ConfigurationDiagnostic] = []

    def report(field: str, message: str, severity: int = logging.WARNING) -> None:
        diagnostic = ConfigurationDiagnostic(file=file, field=field, message=message, severity=severity)
        diagnostics.append(diagnostic)
        if severity >= logging.ERROR:
            fatal_diagnostics.append(diagnostic)

    def finish_diagnostics() -> None:
        for diagnostic in diagnostics:
            if diagnostic.severity >= logging.WARNING:
                _LOGGER.log(diagnostic.severity, "%s", diagnostic)

    try:
        contents = file.read_text(encoding="utf-8")
        data = load_yaml(contents, allow_non_string_keys=True)
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

    palette = _parse_palette(data, report)

    display_backends = _parse_destinations(data, report)
    configured_aspects = tuple(
        sorted({output.output_specification.aspect_ratio for backend in display_backends for output in backend.outputs})
    )
    day_start, reveal = _parse_scheduling(data, report)
    content_directory, storage = _parse_storage(data, file, report)
    presentation_insets, information_view_duration, qr_enabled = _parse_presentation(data, report, configured_aspects)

    package_root = files("refrain")
    fonts_data = _mapping(data.get("fonts", {}), "fonts", report)
    font_registry, font_pools, default_fonts, font_faces = _load_font_resources(fonts_data, file, package_root, report)
    backgrounds_data = _mapping(data.get("backgrounds", {}), "backgrounds", report)
    background_registry, background_pools, default_backgrounds = _load_background_resources(
        backgrounds_data, file, package_root, report
    )
    decorations_data = _mapping(data.get("decorations", {}), "decorations", report)
    (
        decoration_registry,
        decoration_pools,
        default_decorations,
        decoration_color_pools,
        default_decoration_colors,
    ) = _load_decoration_resources(
        decorations_data,
        file,
        package_root,
        font_registry,
        background_registry,
        palette,
        configured_aspects,
        report,
    )
    text_data = _mapping(data.get("text", {}), "text", report)
    text_color_pools, default_text_colors, min_font_size, max_font_size = _load_text_settings(
        text_data, palette, report
    )

    _validate_destination_override_resources(data, font_registry, palette, report)

    finish_diagnostics()
    if fatal_diagnostics:
        raise ApplicationConfigurationError(tuple(fatal_diagnostics))

    assert display_backends
    return ApplicationConfiguration(
        file=file,
        display_backends=display_backends,
        day_start=day_start,
        content_directory=content_directory,
        storage=storage,
        reveal=reveal,
        presentation_insets=presentation_insets,
        fonts=MappingProxyType(font_registry),
        default_fonts=default_fonts,
        min_font_size=min_font_size,
        max_font_size=max_font_size,
        information_view_duration=information_view_duration,
        qr_enabled=qr_enabled,
        backgrounds=MappingProxyType(background_registry),
        default_backgrounds=default_backgrounds,
        decorations=MappingProxyType(decoration_registry),
        default_decorations=default_decorations,
        font_faces=font_faces,
        palette=MappingProxyType(palette),
        default_text_colors=default_text_colors,
        default_decoration_colors=default_decoration_colors,
        font_pools=font_pools,
        background_pools=background_pools,
        decoration_pools=decoration_pools,
        text_color_pools=text_color_pools,
        decoration_color_pools=decoration_color_pools,
    )

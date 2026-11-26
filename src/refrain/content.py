"""Load and validate Refrain content entries."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import time
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Optional, Union

import yaml

from ._filesystem import is_redirected
from ._yaml import load_yaml, yaml_error_location

_ENTRY_FIELDS = {
    "id",
    "quotations",
    "actions",
    "qr",
    "source",
    "attribution",
    "priority",
    "font",
    "background",
    "decoration",
    "text_color",
    "decoration_color",
    "presentation_style",
    "eligibility",
    "reveal",
    "font_faces",
}
_REVEAL_FIELDS = {"source", "attribution"}
_FONT_ROLES = {"quotation", "source", "attribution"}
_ELIGIBILITY_FIELDS = {"ordinary", "year", "month", "day"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_POOL_REFERENCE = re.compile(r"@[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_PRESENTATION_STYLES = {"centered", "left-aligned"}
_ACTION_VISIBILITIES = {"external", "internal"}
_MAX_ACTIONS = 100
_MAX_ACTION_PAYLOAD_BYTES = 10_240
_QR_AUDIENCES = ("external", "internal")
_MAX_QR_PAYLOAD_BYTES = 62
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContentDiagnostic:
    """A content-library validation issue tied to a file and field."""

    file: Path
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}: {self.field}: {self.message}"


class ContentLibraryError(Exception):
    """Raised when one or more content files cannot be accepted."""

    def __init__(self, diagnostics: tuple[ContentDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(diagnostic) for diagnostic in diagnostics))


@dataclass(frozen=True)
class Quotation:
    """A quotation's original text and normalized identity."""

    text: str
    identity: str


@dataclass(frozen=True)
class ContentAction:
    """An opaque, entry-level action declaration."""

    type: str
    visibility: tuple[str, ...]
    payload: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not _IDENTIFIER.fullmatch(self.type):
            raise ValueError("type must be a nonempty ASCII identifier")
        if not isinstance(self.visibility, (list, tuple)) or not self.visibility:
            raise ValueError("visibility must be a nonempty sequence")
        visibility = tuple(self.visibility)
        if any(not isinstance(item, str) or item not in _ACTION_VISIBILITIES for item in visibility):
            raise ValueError("visibility values must be 'external' or 'internal'")
        if len(set(visibility)) != len(visibility):
            raise ValueError("visibility values must not contain duplicates")
        object.__setattr__(self, "visibility", visibility)
        if not isinstance(self.payload, str):
            raise ValueError("payload must be a string")
        try:
            payload_size = len(self.payload.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ValueError("payload must be valid UTF-8 text") from error
        if payload_size > _MAX_ACTION_PAYLOAD_BYTES:
            raise ValueError(f"payload must not exceed {_MAX_ACTION_PAYLOAD_BYTES:,} UTF-8 bytes")


def validate_qr_payload(payload: object) -> str | None:
    """Validate an opaque QR payload, retaining its exact text or explicit null."""
    if payload is None:
        return None
    if not isinstance(payload, str) or not payload:
        raise ValueError("payload must be a nonempty string or null")
    try:
        size = len(payload.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ValueError("payload must be valid UTF-8 text") from error
    if size > _MAX_QR_PAYLOAD_BYTES:
        raise ValueError(f"payload must not exceed {_MAX_QR_PAYLOAD_BYTES} UTF-8 bytes")
    return payload


@dataclass(frozen=True)
class ContentQRDeclaration:
    """One audience's opaque QR payload or explicit suppression."""

    visibility: tuple[str, ...]
    payload: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.visibility, (tuple, list))
            or len(self.visibility) != 1
            or self.visibility[0] not in _QR_AUDIENCES
        ):
            raise ValueError("visibility must contain exactly one audience: 'external' or 'internal'")
        object.__setattr__(self, "visibility", tuple(self.visibility))
        validate_qr_payload(self.payload)


def resolve_qr_payloads(
    defaults: Mapping[str, str | None],
    declarations: tuple[ContentQRDeclaration, ...] = (),
    *,
    overrides: Mapping[str, str | None] | None = None,
) -> tuple[ContentQRDeclaration, ...]:
    """Resolve viewer, entry and configuration precedence independently per audience.

    Omitted keys inherit; explicit null suppresses. The returned declarations contain
    only non-null payloads, ordered external then internal, ready for a checkpoint.
    Explicit override values must already be valid; invalid inputs raise ValueError.
    """
    resolved: dict[str, str | None] = {audience: None for audience in _QR_AUDIENCES}
    for audience, payload in defaults.items():
        if audience not in _QR_AUDIENCES:
            raise ValueError(f"unsupported QR audience: {audience!r}")
        resolved[audience] = validate_qr_payload(payload)
    seen: set[str] = set()
    for declaration in declarations:
        if not isinstance(declaration, ContentQRDeclaration):
            raise ValueError("QR declarations must be ContentQRDeclaration values")
        audience = declaration.visibility[0]
        if audience in seen:
            raise ValueError(f"duplicate QR audience: {audience!r}")
        seen.add(audience)
        resolved[audience] = declaration.payload
    if overrides is not None:
        for audience, payload in overrides.items():
            if audience not in _QR_AUDIENCES:
                raise ValueError(f"unsupported QR audience: {audience!r}")
            resolved[audience] = validate_qr_payload(payload)
    return tuple(
        ContentQRDeclaration((audience,), payload) for audience, payload in resolved.items() if payload is not None
    )


@dataclass(frozen=True)
class EligibilityRule:
    """One intrinsic eligibility condition; it is not evaluated against a date."""

    ordinary: bool = False
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None


@dataclass(frozen=True)
class RevealOverrides:
    """Optional entry-level reveal times awaiting application-configuration resolution."""

    source: Optional[time] = None
    attribution: Optional[time] = None


@dataclass(frozen=True)
class ContentEntry:
    """Entry metadata shared by its quotation candidates.

    Instances returned by ``load_content_library`` are validated; direct
    construction does not validate field values.
    """

    id: str
    quotations: tuple[Quotation, ...]
    source: Optional[str] = None
    attribution: Optional[str] = None
    priority: int = 0
    font: Optional[str] = None
    eligibility: tuple[EligibilityRule, ...] = (EligibilityRule(ordinary=True),)
    reveal: RevealOverrides = RevealOverrides()
    file: Optional[Path] = None
    presentation_style: str = "centered"
    background: Optional[str] = None
    decoration: Optional[str] = None
    font_faces: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    text_color: tuple[str, ...] | None = None
    decoration_color: tuple[str, ...] | None = None
    actions: tuple[ContentAction, ...] = ()
    qr: tuple[ContentQRDeclaration, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.actions, (tuple, list)) or any(
            not isinstance(action, ContentAction) for action in self.actions
        ):
            raise TypeError("actions must be a sequence of ContentAction values")
        object.__setattr__(self, "actions", tuple(self.actions))
        if not isinstance(self.qr, (tuple, list)) or any(
            not isinstance(declaration, ContentQRDeclaration) for declaration in self.qr
        ):
            raise TypeError("qr must be a sequence of ContentQRDeclaration values")
        object.__setattr__(self, "qr", tuple(self.qr))


def normalize_quotation(text: str) -> str:
    """Return the architecture-defined identity form without changing display text."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _diagnose(diagnostics: list[ContentDiagnostic], file: Path, field: str, message: str) -> None:
    diagnostics.append(ContentDiagnostic(file=file, field=field, message=message))


@lru_cache(maxsize=2048)
def _log_diagnostic_once(message: str, level: int, file_state: tuple[int, int] | None) -> None:
    _LOGGER.log(level, "%s", message)


def _log_diagnostic(diagnostic: ContentDiagnostic, level: int, *, entry_excluded: bool = True) -> None:
    message = str(diagnostic)
    if level == logging.WARNING and entry_excluded and "excluded" not in diagnostic.message:
        message += "; this entry is excluded"
    try:
        stat = diagnostic.file.stat()
        file_state = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        file_state = None
    _log_diagnostic_once(message, level, file_state)


def _validate_actions(value: object, file: Path) -> tuple[ContentAction, ...]:
    if not isinstance(value, list):
        _log_diagnostic(
            ContentDiagnostic(file, "actions", "must be a sequence; all actions are ignored"),
            logging.WARNING,
            entry_excluded=False,
        )
        return ()

    actions: list[ContentAction] = []
    for index, member in enumerate(value):
        if len(actions) == _MAX_ACTIONS:
            _log_diagnostic(
                ContentDiagnostic(
                    file,
                    "actions",
                    f"actions after the first {_MAX_ACTIONS} valid actions are ignored",
                ),
                logging.WARNING,
                entry_excluded=False,
            )
            break
        field_name = f"actions[{index}]"
        if not isinstance(member, Mapping):
            _log_diagnostic(
                ContentDiagnostic(file, field_name, "must be a mapping; this action is ignored"),
                logging.WARNING,
                entry_excluded=False,
            )
            continue

        supported_fields = {"type", "visibility", "payload"}
        unsupported_fields = [key for key in member if not isinstance(key, str) or key not in supported_fields]
        missing_fields = {"type", "visibility"} - member.keys()
        if unsupported_fields or missing_fields:
            details = []
            if missing_fields:
                details.append(f"missing fields: {', '.join(sorted(missing_fields))}")
            if unsupported_fields:
                details.append(f"unsupported fields: {', '.join(sorted(unsupported_fields, key=repr))}")
            _log_diagnostic(
                ContentDiagnostic(file, field_name, f"{'; '.join(details)}; this action is ignored"),
                logging.WARNING,
                entry_excluded=False,
            )
            continue

        visibility = member["visibility"]
        if not isinstance(visibility, list):
            reason = "visibility must be a nonempty sequence"
        else:
            try:
                action = ContentAction(
                    type=member["type"],  # type: ignore[arg-type]
                    visibility=tuple(visibility),
                    payload=member.get("payload", ""),  # type: ignore[arg-type]
                )
            except (TypeError, ValueError) as error:
                reason = str(error)
            else:
                actions.append(action)
                continue
        _log_diagnostic(
            ContentDiagnostic(file, field_name, f"{reason}; this action is ignored"),
            logging.WARNING,
            entry_excluded=False,
        )
    return tuple(actions)


def _validate_qr(value: object, file: Path) -> tuple[ContentQRDeclaration, ...]:
    if not isinstance(value, list):
        _log_diagnostic(
            ContentDiagnostic(file, "qr", "must be a sequence; all QR declarations are ignored"),
            logging.WARNING,
            entry_excluded=False,
        )
        return ()

    declarations: list[ContentQRDeclaration] = []
    seen: set[str] = set()
    for index, member in enumerate(value):
        field_name = f"qr[{index}]"
        try:
            if not isinstance(member, Mapping) or set(member) != {"visibility", "payload"}:
                raise ValueError("must be a mapping with exactly visibility and payload fields")
            if not isinstance(member["visibility"], list):
                raise ValueError("visibility must be a sequence containing exactly one audience")
            declaration = ContentQRDeclaration(member["visibility"], member["payload"])
            audience = declaration.visibility[0]
            if audience in seen:
                raise ValueError(f"duplicate {audience!r} audience")
        except (TypeError, ValueError) as error:
            _log_diagnostic(
                ContentDiagnostic(file, field_name, f"{error}; this QR declaration is ignored"),
                logging.WARNING,
                entry_excluded=False,
            )
            continue
        declarations.append(declaration)
        seen.add(audience)
    return tuple(declarations)


def _validate_calendar_rule(
    values: dict[str, object], field: str, file: Path, diagnostics: list[ContentDiagnostic]
) -> Optional[EligibilityRule]:
    keys = set(values)
    if keys == {"ordinary"}:
        if values["ordinary"] is not True:
            _diagnose(diagnostics, file, f"{field}.ordinary", "must be the boolean value true")
            return None
        return EligibilityRule(ordinary=True)

    supported_combinations = ({"year", "month", "day"}, {"month", "day"}, {"day"}, {"month"})
    if keys not in supported_combinations:
        _diagnose(diagnostics, file, field, "uses an unsupported eligibility field combination")
        return None

    valid = True
    for key in sorted(keys):
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, int):
            _diagnose(diagnostics, file, f"{field}.{key}", "must be an integer")
            valid = False
        elif key == "year" and value < 1:
            _diagnose(diagnostics, file, f"{field}.{key}", "must be a positive integer")
            valid = False
        elif key == "month" and not 1 <= value <= 12:
            _diagnose(diagnostics, file, f"{field}.{key}", "must be an integer from 1 through 12")
            valid = False
        elif key == "day" and not 1 <= value <= 31:
            _diagnose(diagnostics, file, f"{field}.{key}", "must be an integer from 1 through 31")
            valid = False
    if not valid:
        return None

    year = values.get("year")
    month = values.get("month")
    day = values.get("day")
    calendar_year = year if isinstance(year, int) else None
    calendar_month = month if isinstance(month, int) else None
    calendar_day = day if isinstance(day, int) else None
    if calendar_month is not None and calendar_day is not None:
        month_lengths = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        maximum_day = month_lengths[calendar_month - 1]
        if calendar_year is not None:
            is_leap_year = calendar_year % 4 == 0 and (calendar_year % 100 != 0 or calendar_year % 400 == 0)
            if calendar_month == 2 and not is_leap_year:
                maximum_day -= 1
        if calendar_day > maximum_day:
            _diagnose(diagnostics, file, field, "does not describe a valid calendar date")
            return None

    return EligibilityRule(
        year=calendar_year,
        month=calendar_month,
        day=calendar_day,
    )


def _validate_eligibility(
    value: object, file: Path, diagnostics: list[ContentDiagnostic]
) -> Optional[tuple[EligibilityRule, ...]]:
    if not isinstance(value, list):
        _diagnose(diagnostics, file, "eligibility", "must be a sequence of eligibility-rule mappings")
        return None
    if not value:
        _diagnose(diagnostics, file, "eligibility", "must contain at least one rule")
        return None

    rules: list[EligibilityRule] = []
    for index, rule in enumerate(value):
        field = f"eligibility[{index}]"
        if not isinstance(rule, dict):
            _diagnose(diagnostics, file, field, "must be a mapping")
            continue
        for key in sorted(rule.keys() - _ELIGIBILITY_FIELDS):
            _diagnose(diagnostics, file, f"{field}.{key}", "is not a supported eligibility field")
        if rule.keys() - _ELIGIBILITY_FIELDS:
            continue
        validated = _validate_calendar_rule(rule, field, file, diagnostics)
        if validated is not None:
            rules.append(validated)
    if len(rules) != len(value):
        return None
    return tuple(rules)


def _validate_reveal(value: object, file: Path, diagnostics: list[ContentDiagnostic]) -> Optional[RevealOverrides]:
    if not isinstance(value, dict):
        _diagnose(diagnostics, file, "reveal", "must be a mapping")
        return None

    parsed: dict[str, Optional[time]] = {"source": None, "attribution": None}
    valid = True
    for key, reveal_value in value.items():
        if key not in _REVEAL_FIELDS:
            _diagnose(diagnostics, file, f"reveal.{key}", "is not a supported reveal override")
            valid = False
        elif not isinstance(reveal_value, str) or not _TIME.fullmatch(reveal_value):
            _diagnose(diagnostics, file, f"reveal.{key}", "must be a valid HH:MM local time")
            valid = False
        else:
            parsed[key] = time.fromisoformat(reveal_value)
    if not valid:
        return None
    return RevealOverrides(source=parsed["source"], attribution=parsed["attribution"])


def _validate_font_faces(
    value: object, file: Path, diagnostics: list[ContentDiagnostic]
) -> Optional[Mapping[str, str]]:
    if not isinstance(value, dict):
        _diagnose(diagnostics, file, "font_faces", "must be a mapping of literary roles to face identifiers")
        return None
    valid = True
    for role, face in value.items():
        field = f"font_faces.{role}" if isinstance(role, str) else f"font_faces[{role!r}]"
        if not isinstance(role, str) or role not in _FONT_ROLES:
            _diagnose(diagnostics, file, field, "is not a supported literary role")
            valid = False
        elif not isinstance(face, str) or not _IDENTIFIER.fullmatch(face):
            _diagnose(
                diagnostics,
                file,
                field,
                "must be a nonempty ASCII face identifier beginning with a letter or digit",
            )
            valid = False
    if not valid:
        return None
    return MappingProxyType({role: face for role, face in value.items()})


def _validate_color_preference(
    value: object, field: str, file: Path, diagnostics: list[ContentDiagnostic]
) -> tuple[str, ...] | None:
    if isinstance(value, str):
        members = (value,)
    elif isinstance(value, list) and value:
        members = value
    else:
        _diagnose(diagnostics, file, field, "must be a string or a nonempty sequence of color candidates")
        return None

    candidates = []
    for index, member in enumerate(members):
        if isinstance(member, str) and (_IDENTIFIER.fullmatch(member) or _POOL_REFERENCE.fullmatch(member)):
            candidates.append(member)
        else:
            candidate_field = field if isinstance(value, str) else f"{field}[{index}]"
            _log_diagnostic(
                ContentDiagnostic(
                    file,
                    candidate_field,
                    f"invalid color candidate {member!r}; this candidate is excluded",
                ),
                logging.WARNING,
                entry_excluded=False,
            )
    return tuple(candidates)


def _validate_entry(data: object, file: Path, diagnostics: list[ContentDiagnostic]) -> Optional[ContentEntry]:
    initial_diagnostic_count = len(diagnostics)
    if not isinstance(data, dict):
        _diagnose(diagnostics, file, "$", "must contain one top-level mapping")
        return None

    for key in sorted(data.keys() - _ENTRY_FIELDS):
        _diagnose(diagnostics, file, key, "is not a supported content-entry field")

    entry_id = data.get("id")
    if not isinstance(entry_id, str) or not _IDENTIFIER.fullmatch(entry_id):
        _diagnose(
            diagnostics,
            file,
            "id",
            "must start with an ASCII letter or digit and contain only ASCII letters, digits, hyphens, or underscores",
        )

    quotation_values = data.get("quotations")
    quotations: list[Quotation] = []
    if not isinstance(quotation_values, list) or not quotation_values:
        _diagnose(diagnostics, file, "quotations", "must be a nonempty sequence of strings")
    else:
        for index, value in enumerate(quotation_values):
            field = f"quotations[{index}]"
            if not isinstance(value, str):
                _diagnose(diagnostics, file, field, "must be a string")
            elif not value.strip():
                _diagnose(diagnostics, file, field, "must contain meaningful text")
            else:
                quotations.append(Quotation(text=value, identity=normalize_quotation(value)))

    optional_strings: dict[str, Optional[str]] = {}
    for field in ("source", "attribution"):
        value = data.get(field)
        if field not in data:
            optional_strings[field] = None
        elif not isinstance(value, str) or not value.strip():
            _diagnose(diagnostics, file, field, "must be a nonblank string when supplied")
        else:
            optional_strings[field] = value

    font = data.get("font")
    if "font" not in data:
        optional_strings["font"] = None
    elif (
        not isinstance(font, str)
        or font == "none"
        or not (_IDENTIFIER.fullmatch(font) or _POOL_REFERENCE.fullmatch(font))
    ):
        _diagnose(
            diagnostics,
            file,
            "font",
            "must be a font-bundle identifier or @font-pool reference; 'none' is not permitted",
        )
    else:
        optional_strings["font"] = font

    background = data.get("background")
    if "background" in data and (
        not isinstance(background, str)
        or not (_IDENTIFIER.fullmatch(background) or _POOL_REFERENCE.fullmatch(background))
    ):
        _diagnose(diagnostics, file, "background", "must be a resource identifier or pool reference")

    decoration = data.get("decoration")
    if "decoration" in data and (
        not isinstance(decoration, str)
        or not (_IDENTIFIER.fullmatch(decoration) or _POOL_REFERENCE.fullmatch(decoration))
    ):
        _diagnose(diagnostics, file, "decoration", "must be a resource identifier or pool reference")

    text_color = (
        _validate_color_preference(data["text_color"], "text_color", file, diagnostics)
        if "text_color" in data
        else None
    )
    decoration_color = (
        _validate_color_preference(data["decoration_color"], "decoration_color", file, diagnostics)
        if "decoration_color" in data
        else None
    )

    priority = data.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        _diagnose(diagnostics, file, "priority", "must be a signed integer (booleans are not valid priorities)")

    presentation_style = data.get("presentation_style", "centered")
    if not isinstance(presentation_style, str) or presentation_style not in _PRESENTATION_STYLES:
        _diagnose(diagnostics, file, "presentation_style", "must be one of 'centered' or 'left-aligned'")

    eligibility = (
        _validate_eligibility(data["eligibility"], file, diagnostics)
        if "eligibility" in data
        else (EligibilityRule(ordinary=True),)
    )
    reveal = _validate_reveal(data["reveal"], file, diagnostics) if "reveal" in data else RevealOverrides()
    font_faces = (
        _validate_font_faces(data["font_faces"], file, diagnostics) if "font_faces" in data else MappingProxyType({})
    )
    actions = _validate_actions(data["actions"], file) if "actions" in data else ()
    qr = _validate_qr(data["qr"], file) if "qr" in data else ()

    if len(diagnostics) != initial_diagnostic_count:
        return None
    return ContentEntry(
        id=entry_id,  # type: ignore[arg-type]
        quotations=tuple(quotations),
        source=optional_strings["source"],
        attribution=optional_strings["attribution"],
        priority=priority,  # type: ignore[arg-type]
        font=optional_strings["font"],
        presentation_style=presentation_style,  # type: ignore[arg-type]
        eligibility=eligibility,  # type: ignore[arg-type]
        reveal=reveal,  # type: ignore[arg-type]
        file=file,
        background=background,  # type: ignore[arg-type]
        decoration=decoration,  # type: ignore[arg-type]
        font_faces=font_faces,  # type: ignore[arg-type]
        text_color=text_color,
        decoration_color=decoration_color,
        actions=actions,
        qr=qr,
    )


def load_content_library(content_directory: Union[str, Path]) -> tuple[ContentEntry, ...]:
    """Load and validate every ``.yaml`` or ``.yml`` entry in a directory tree.

    Invalid files and entries are excluded independently. A ``ContentLibraryError``
    is raised when discovery fails or no valid quotation remains. Reveal overrides
    are checked for syntax only; effective timing is resolved separately.
    """
    return _load_content_library(content_directory)


def _load_effective_content_library(
    content_directory: Union[str, Path],
    *,
    day_start: time,
    reveal_schedule: Mapping[str, time],
) -> tuple[ContentEntry, ...]:
    """Load entries after validating their effective reveal schedule."""

    def validate_effective_schedule(entry: ContentEntry) -> tuple[ContentDiagnostic, ...]:
        assert entry.file is not None
        diagnostics: list[ContentDiagnostic] = []
        for field_name in ("source", "attribution"):
            override = getattr(entry.reveal, field_name)
            effective_time = override if override is not None else reveal_schedule[field_name]
            if effective_time < day_start:
                _diagnose(
                    diagnostics,
                    entry.file,
                    f"reveal.{field_name}",
                    f"effective time {effective_time:%H:%M} precedes configured day start "
                    f"{day_start:%H:%M}; this entry is excluded",
                )
        return tuple(diagnostics)

    return _load_content_library(
        content_directory,
        effective_schedule_validator=validate_effective_schedule,
    )


def _load_content_library(
    content_directory: Union[str, Path],
    *,
    effective_schedule_validator: Callable[[ContentEntry], tuple[ContentDiagnostic, ...]] | None = None,
) -> tuple[ContentEntry, ...]:
    directory = Path(content_directory)
    try:
        is_directory = directory.is_dir()
    except OSError as error:
        diagnostic = ContentDiagnostic(directory, "$", f"cannot access content directory: {error}")
        _log_diagnostic(diagnostic, logging.ERROR)
        raise ContentLibraryError((diagnostic,)) from error
    if not is_directory:
        diagnostic = ContentDiagnostic(directory, "$", "content directory does not exist or is not a directory")
        _log_diagnostic(diagnostic, logging.ERROR)
        raise ContentLibraryError((diagnostic,))

    discovery_diagnostics: list[ContentDiagnostic] = []
    files: list[Path] = []
    inspection_errors: dict[Path, OSError] = {}

    def report_walk_error(error: OSError) -> None:
        affected_path = Path(error.filename) if error.filename else directory
        _diagnose(discovery_diagnostics, affected_path, "$", f"cannot enumerate content directory: {error}")

    try:
        for root, directories, filenames in os.walk(directory, onerror=report_walk_error):
            for name in directories[:]:
                try:
                    if is_redirected(Path(root) / name):
                        directories.remove(name)
                except OSError as error:
                    directories.remove(name)
                    report_walk_error(error)
            for filename in filenames:
                if Path(filename).suffix.lower() not in {".yaml", ".yml"}:
                    continue
                file = Path(root) / filename
                try:
                    if is_redirected(file):
                        continue
                except OSError as error:
                    inspection_errors[file] = error
                files.append(file)
    except OSError as error:
        report_walk_error(error)
    if discovery_diagnostics:
        for diagnostic in discovery_diagnostics:
            _log_diagnostic(diagnostic, logging.ERROR)
        raise ContentLibraryError(tuple(discovery_diagnostics))

    if not files:
        diagnostic = ContentDiagnostic(
            directory,
            "$",
            "no YAML content files were found; add at least one valid content entry",
        )
        _log_diagnostic(diagnostic, logging.ERROR)
        raise ContentLibraryError((diagnostic,))

    rejected_diagnostics: list[ContentDiagnostic] = []
    entries: list[ContentEntry] = []
    for file in sorted(files):
        file_diagnostics: list[ContentDiagnostic] = []
        try:
            if file in inspection_errors:
                raise inspection_errors[file]
            contents = file.read_text(encoding="utf-8")
            data = load_yaml(contents)
        except (OSError, UnicodeError) as error:
            _diagnose(file_diagnostics, file, "$", f"cannot read UTF-8 YAML file: {error}; this file is excluded")
            rejected_diagnostics.extend(file_diagnostics)
            continue
        except yaml.YAMLError as error:
            location = yaml_error_location(error)
            detail = f"{location}: {error}" if location else str(error)
            _diagnose(file_diagnostics, file, "$", f"invalid or unsupported YAML: {detail}; this file is excluded")
            rejected_diagnostics.extend(file_diagnostics)
            continue

        entry = _validate_entry(data, file, file_diagnostics)
        if entry is None:
            rejected_diagnostics.extend(file_diagnostics)
            continue
        if effective_schedule_validator is not None:
            file_diagnostics.extend(effective_schedule_validator(entry))
            if file_diagnostics:
                rejected_diagnostics.extend(file_diagnostics)
                continue
        entries.append(entry)

    by_identifier: dict[str, list[ContentEntry]] = {}
    for entry in entries:
        by_identifier.setdefault(entry.id, []).append(entry)

    accepted_entries: list[ContentEntry] = []
    for identifier, matching_entries in sorted(by_identifier.items()):
        if len(matching_entries) == 1:
            accepted_entries.extend(matching_entries)
            continue
        conflicting_files = sorted(entry.file for entry in matching_entries if entry.file is not None)
        for entry in matching_entries:
            assert entry.file is not None
            peers = ", ".join(str(path) for path in conflicting_files if path != entry.file)
            _diagnose(
                rejected_diagnostics,
                entry.file,
                "id",
                f"conflicting duplicate identifier {identifier!r}; this entry is excluded with {peers}",
            )

    for diagnostic in rejected_diagnostics:
        _log_diagnostic(diagnostic, logging.WARNING)

    if not accepted_entries:
        diagnostic = ContentDiagnostic(
            directory,
            "$",
            "content library contains no valid quotations; correct or add a valid content entry",
        )
        _log_diagnostic(diagnostic, logging.ERROR)
        raise ContentLibraryError((*rejected_diagnostics, diagnostic))
    return tuple(sorted(accepted_entries, key=lambda entry: entry.file or Path()))

"""Load and validate Refrain content entries."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

import yaml

from ._yaml import load_yaml, yaml_error_location

_ENTRY_FIELDS = {
    "id",
    "quotations",
    "source",
    "attribution",
    "priority",
    "font",
    "presentation_style",
    "eligibility",
    "reveal",
}
_REVEAL_FIELDS = {"source", "attribution"}
_ELIGIBILITY_FIELDS = {"ordinary", "year", "month", "day"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_PRESENTATION_STYLES = {"centered", "left-aligned"}
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


def normalize_quotation(text: str) -> str:
    """Return the architecture-defined identity form without changing display text."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _diagnose(diagnostics: list[ContentDiagnostic], file: Path, field: str, message: str) -> None:
    diagnostics.append(ContentDiagnostic(file=file, field=field, message=message))


@lru_cache(maxsize=2048)
def _log_diagnostic_once(message: str, level: int) -> None:
    _LOGGER.log(level, "%s", message)


def _log_diagnostic(diagnostic: ContentDiagnostic, level: int) -> None:
    _log_diagnostic_once(str(diagnostic), level)


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
    for field in ("source", "attribution", "font"):
        value = data.get(field)
        if field not in data:
            optional_strings[field] = None
        elif not isinstance(value, str) or value == "":
            _diagnose(diagnostics, file, field, "must be a nonempty string when supplied")
        else:
            optional_strings[field] = value

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
    )


def load_content_library(content_directory: Union[str, Path]) -> tuple[ContentEntry, ...]:
    """Load and validate every ``.yaml`` or ``.yml`` entry in a directory tree.

    Invalid files and entries are excluded independently. A ``ContentLibraryError``
    is raised when discovery fails or no valid quotation remains.
    """
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

    def report_walk_error(error: OSError) -> None:
        affected_path = Path(error.filename) if error.filename else directory
        _diagnose(discovery_diagnostics, affected_path, "$", f"cannot enumerate content directory: {error}")

    try:
        for root, _, filenames in os.walk(directory, onerror=report_walk_error):
            files.extend(
                Path(root) / filename for filename in filenames if Path(filename).suffix.lower() in {".yaml", ".yml"}
            )
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

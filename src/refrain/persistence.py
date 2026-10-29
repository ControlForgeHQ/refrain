"""Versioned, atomic persistence for committed quotation selection state."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .content import normalize_quotation
from .selection import SelectionProposal

_FORMAT_VERSION = 3
_DEFAULT_HISTORY_SEGMENT_SIZE = 1_048_576
_DEFAULT_HISTORY_MAX_SEGMENTS = 20
_DAY_START = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PersistentStateError(Exception):
    """Base class for persistent-state failures."""


class StateRecoveryError(PersistentStateError):
    """Raised when existing persistent state cannot be safely recovered."""


class UnsupportedStateVersionError(StateRecoveryError):
    """Raised when a state file uses an unsupported format version."""


class StateCommitError(PersistentStateError):
    """Raised when a state commit fails; ``published`` indicates rename status."""

    def __init__(self, message: str, *, published: bool = False) -> None:
        self.published = published
        super().__init__(message)


class GlobalHistoryWriteError(PersistentStateError):
    """Raised when a best-effort global-history operation fails."""


def _freeze_json(value: object, field: str) -> object:
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field} keys must be strings")
            frozen[key] = _freeze_json(item, f"{field}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{field}[{index}]") for index, item in enumerate(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"{field} must contain only finite JSON-compatible values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _valid_identity(value: object, field: str) -> str:
    identity = _nonempty_string(value, field)
    if normalize_quotation(identity) != identity:
        raise ValueError(f"{field} must be a normalized quotation identity")
    return identity


@dataclass(frozen=True)
class ResolvedFont:
    """Font bytes resolved from a stable identifier for image preparation."""

    identifier: str
    data: bytes

    def __post_init__(self) -> None:
        _nonempty_string(self.identifier, "font identifier")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("font data must be nonempty bytes")

    @property
    def sha256(self) -> str:
        """Return the digest of the preserved font contents."""
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class SchedulingContext:
    """Resolved scheduling inputs associated with one committed display date."""

    display_date: date
    timezone: str
    day_start: str

    def __post_init__(self) -> None:
        if not isinstance(self.display_date, date) or isinstance(self.display_date, datetime):
            raise ValueError("display_date must be a date")
        _nonempty_string(self.timezone, "scheduling timezone")
        if not isinstance(self.day_start, str) or not _DAY_START.fullmatch(self.day_start):
            raise ValueError("day_start must be a valid HH:MM time")


@dataclass(frozen=True)
class DailySnapshot:
    """Self-contained resolved presentation data for one selected quotation."""

    quotation_text: str
    quotation_identity: str
    font_identifier: str
    presentation_metadata: Mapping[str, Any]
    reveal_schedule: Mapping[str, Any]
    layout: Mapping[str, Any]
    scheduling: SchedulingContext

    def __post_init__(self) -> None:
        _nonempty_string(self.quotation_text, "quotation_text")
        _valid_identity(self.quotation_identity, "quotation_identity")
        if normalize_quotation(self.quotation_text) != self.quotation_identity:
            raise ValueError("quotation_identity must match the normalized quotation_text")
        _nonempty_string(self.font_identifier, "font_identifier")
        if not isinstance(self.scheduling, SchedulingContext):
            raise TypeError("scheduling must be a SchedulingContext")
        for field in ("presentation_metadata", "reveal_schedule", "layout"):
            value = getattr(self, field)
            if not isinstance(value, Mapping):
                raise TypeError(f"{field} must be a mapping")
            object.__setattr__(self, field, _freeze_json(value, field))

    @property
    def display_date(self) -> date:
        """Return the display date recorded by the scheduling context."""
        return self.scheduling.display_date


@dataclass(frozen=True)
class GlobalHistoryRecord:
    """One chronologically ordered committed selection."""

    revision: int
    display_date: date
    selection_timestamp: datetime
    quotation_text: str
    quotation_identity: str
    font_identifier: str


@dataclass(frozen=True)
class PersistentState:
    """An immutable snapshot, its reveal progress, and repetition history."""

    revision: int
    snapshot: DailySnapshot
    repetition_history: frozenset[str]
    highest_reveal_stage: int


class GlobalHistoryStore:
    """Append committed selection events to a separately retained JSONL log."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_segment_size: int = _DEFAULT_HISTORY_SEGMENT_SIZE,
        max_segments: int = _DEFAULT_HISTORY_MAX_SEGMENTS,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("global-history path must be absolute")
        if type(max_segment_size) is not int or max_segment_size <= 0:
            raise ValueError("max_segment_size must be a positive integer")
        if type(max_segments) is not int or max_segments <= 0:
            raise ValueError("max_segments must be a positive integer")
        self.max_segment_size = max_segment_size
        self.max_segments = max_segments

    def record(self, state: PersistentState, *, timestamp: datetime | None = None) -> GlobalHistoryRecord:
        """Append one event for a committed state, independently of state publication."""
        if not isinstance(state, PersistentState):
            raise TypeError("state must be a PersistentState")
        event_time = datetime.now(timezone.utc) if timestamp is None else timestamp
        if not isinstance(event_time, datetime) or event_time.utcoffset() is None:
            raise ValueError("timestamp must be a timezone-aware datetime")
        event_time = event_time.astimezone(timezone.utc)
        record = GlobalHistoryRecord(
            revision=state.revision,
            display_date=state.snapshot.display_date,
            selection_timestamp=event_time,
            quotation_text=state.snapshot.quotation_text,
            quotation_identity=state.snapshot.quotation_identity,
            font_identifier=state.snapshot.font_identifier,
        )
        contents = _encode_history_record(record)
        if len(contents) > self.max_segment_size:
            raise GlobalHistoryWriteError(
                f"global-history record for revision {record.revision} is larger than the "
                f"{self.max_segment_size}-byte segment limit"
            )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _truncate_incomplete_history_tail(self.path)
            active_size = self.path.stat().st_size if self.path.exists() else 0
            if active_size + len(contents) > self.max_segment_size:
                self._rotate()
            with self.path.open("ab") as history_file:
                written = history_file.write(contents)
                if written != len(contents):
                    raise OSError(f"short write: wrote {written} of {len(contents)} bytes")
                history_file.flush()
                os.fsync(history_file.fileno())
        except OSError as error:
            raise GlobalHistoryWriteError(f"cannot record global history at {self.path}: {error}") from error
        return record

    def _rotate(self) -> None:
        try:
            if self.max_segments == 1:
                self.path.unlink(missing_ok=True)
                return
            oldest = self._segment_path(self.max_segments - 1)
            oldest.unlink(missing_ok=True)
            for index in range(self.max_segments - 2, 0, -1):
                source = self._segment_path(index)
                if source.exists():
                    os.replace(source, self._segment_path(index + 1))
            if self.path.exists():
                os.replace(self.path, self._segment_path(1))
        except OSError as error:
            raise GlobalHistoryWriteError(f"cannot rotate global history at {self.path}: {error}") from error

    def _segment_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.stem}.{index}{self.path.suffix}")


class PersistentStateStore:
    """Load and atomically commit Refrain's complete selection state.

    The path must be absolute. State is stored in one checksummed JSON file;
    replacement and durability behavior are described in ``docs/ENGINEERING.md``.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("persistent-state path must be absolute")

    def load(self) -> PersistentState | None:
        """Return the recovered state, or ``None`` only when no state file exists."""
        try:
            contents = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise StateRecoveryError(f"cannot read persistent state at {self.path}: {error}") from error

        try:
            document = json.loads(contents.decode("utf-8"), object_pairs_hook=_unique_object)
            return _decode_document(document)
        except UnsupportedStateVersionError:
            raise
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise StateRecoveryError(f"invalid persistent state at {self.path}: {error}") from error

    def commit(
        self,
        proposal: SelectionProposal,
        snapshot: DailySnapshot,
        *,
        initial_reveal_stage: int = 0,
    ) -> PersistentState:
        """Commit a proposal, its self-contained snapshot, and proposed repetition history.

        The proposal's ``base_revision`` must identify the state generation
        used to produce it. Repeating the exact same commitment is idempotent.
        A new selection starts at ``initial_reveal_stage``; a retry preserves
        any subsequent reveal progress. Global history is recorded separately.
        The proposal and its history are read only; neither is mutated.
        """
        _validate_reveal_stage(initial_reveal_stage)
        if not isinstance(proposal, SelectionProposal):
            raise TypeError("proposal must be a SelectionProposal")
        if type(proposal.base_revision) is not int or proposal.base_revision < 0:
            raise StateCommitError("proposal base_revision must be a nonnegative integer")
        candidate = proposal.selected_candidate
        if candidate is None:
            raise StateCommitError("cannot commit a proposal without a selected quotation")
        if not isinstance(snapshot, DailySnapshot):
            raise TypeError("snapshot must be a DailySnapshot")
        if (candidate.text, candidate.identity) != (snapshot.quotation_text, snapshot.quotation_identity):
            raise StateCommitError("snapshot quotation text and identity must match the selected candidate")

        try:
            repetition_history = frozenset(proposal.proposed_repetition_history)
        except TypeError as error:
            raise StateCommitError(f"invalid proposed repetition history: {error}") from error
        for identity in repetition_history:
            try:
                _valid_identity(identity, "repetition-history identity")
            except ValueError as error:
                raise StateCommitError(str(error)) from error
        if snapshot.quotation_identity not in repetition_history:
            raise StateCommitError("proposed repetition history must contain the selected quotation identity")

        previous = self.load()
        current_revision = 0 if previous is None else previous.revision
        if previous is not None and current_revision == proposal.base_revision + 1:
            if previous.snapshot == snapshot and previous.repetition_history == repetition_history:
                self._confirm_durability()
                return previous
        if current_revision != proposal.base_revision:
            raise StateCommitError(
                f"stale selection proposal: based on revision {proposal.base_revision}, "
                f"but current state is revision {current_revision}"
            )

        state = PersistentState(
            revision=current_revision + 1,
            snapshot=snapshot,
            repetition_history=repetition_history,
            highest_reveal_stage=initial_reveal_stage,
        )
        _validate_state(state)
        self._publish(state)
        return state

    def advance_reveal_progress(self, expected_revision: int, stage: int) -> PersistentState:
        """Persist a higher stage for the specified current selection generation.

        Same or earlier stages do not rewrite state. They still confirm directory
        durability, allowing retries after a published but unconfirmed update.
        Callers must serialize writers, just as for selection commitment.
        """
        if type(expected_revision) is not int or expected_revision < 1:
            raise StateCommitError("expected_revision must be a positive integer")
        _validate_reveal_stage(stage)
        previous = self.load()
        if previous is None:
            raise StateCommitError("cannot advance reveal progress without a committed selection")
        if previous.revision != expected_revision:
            raise StateCommitError(
                f"stale reveal-progress update: expected revision {expected_revision}, "
                f"but current state is revision {previous.revision}"
            )
        if stage <= previous.highest_reveal_stage:
            self._confirm_durability()
            return previous
        state = replace(previous, highest_reveal_stage=stage)
        self._publish(state)
        return state

    def _confirm_durability(self) -> None:
        try:
            _sync_directory(self.path.parent)
        except OSError as error:
            raise StateCommitError(
                f"cannot confirm persistent-state durability at {self.path}: {error}",
                published=True,
            ) from error

    def _publish(self, state: PersistentState) -> None:
        parent = self.path.parent
        temporary_path: Path | None = None
        published = False
        try:
            _create_parent_directories(parent)
            contents = _encode_document(state)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(contents)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            published = True
            _sync_directory(parent)
        except OSError as error:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            if published:
                status = "the new state was published but directory durability could not be confirmed"
            else:
                status = "the prior state remains authoritative"
            message = f"cannot commit persistent state at {self.path}: {error}; {status}"
            raise StateCommitError(message, published=published) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _validate_reveal_stage(stage: object) -> None:
    if type(stage) is not int or stage < 0:
        raise ValueError("highest_reveal_stage must be a nonnegative integer")


def _require_mapping(value: object, field: str, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    missing = fields - value.keys()
    extra = value.keys() - fields
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unsupported fields: {', '.join(sorted(extra))}")
        raise ValueError(f"{field}: {'; '.join(details)}")
    return value


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD format")
    return parsed


def _decode_snapshot(value: object) -> DailySnapshot:
    data = _require_mapping(
        value,
        "snapshot",
        {
            "quotation_text",
            "quotation_identity",
            "font_identifier",
            "presentation_metadata",
            "reveal_schedule",
            "layout",
            "scheduling",
        },
    )
    scheduling_data = _require_mapping(
        data["scheduling"],
        "snapshot.scheduling",
        {"display_date", "timezone", "day_start"},
    )
    scheduling = SchedulingContext(
        display_date=_parse_date(scheduling_data["display_date"], "snapshot.scheduling.display_date"),
        timezone=_nonempty_string(scheduling_data["timezone"], "snapshot.scheduling.timezone"),
        day_start=scheduling_data["day_start"],
    )
    return DailySnapshot(
        quotation_text=data["quotation_text"],
        quotation_identity=data["quotation_identity"],
        font_identifier=_nonempty_string(data["font_identifier"], "snapshot.font_identifier"),
        presentation_metadata=data["presentation_metadata"],
        reveal_schedule=data["reveal_schedule"],
        layout=data["layout"],
        scheduling=scheduling,
    )


def _decode_document(value: object) -> PersistentState:
    document = _require_mapping(value, "state document", {"format_version", "state", "sha256"})
    version = document["format_version"]
    if type(version) is not int:
        raise StateRecoveryError("persistent-state format_version must be an integer")
    if version != _FORMAT_VERSION:
        raise UnsupportedStateVersionError(
            f"unsupported persistent-state format version {version}; version 3 is required. "
            "Archive or remove this development state file before starting Refrain; it was not modified."
        )
    payload = document["state"]
    digest = document["sha256"]
    if not isinstance(payload, dict):
        raise ValueError("state document state must be an object")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError("state document sha256 must be a lowercase SHA-256 digest")
    expected_digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if not hmac.compare_digest(digest, expected_digest):
        raise ValueError("state document checksum does not match its contents")

    data = _require_mapping(payload, "state", {"revision", "snapshot", "repetition_history", "highest_reveal_stage"})
    repetition_data = data["repetition_history"]
    if not isinstance(repetition_data, list) or not all(isinstance(item, str) for item in repetition_data):
        raise ValueError("state.repetition_history must be an array of normalized identities")
    if repetition_data != sorted(set(repetition_data)):
        raise ValueError("state.repetition_history must contain unique, sorted identities")

    if type(data["revision"]) is not int or data["revision"] <= 0:
        raise ValueError("state.revision must be a positive integer")
    snapshot = _decode_snapshot(data["snapshot"])
    state = PersistentState(
        revision=data["revision"],
        snapshot=snapshot,
        repetition_history=frozenset(_valid_identity(item, "repetition-history identity") for item in repetition_data),
        highest_reveal_stage=data["highest_reveal_stage"],
    )
    _validate_state(state)
    return state


def _validate_state(state: PersistentState) -> None:
    if type(state.revision) is not int or state.revision <= 0:
        raise ValueError("revision must be a positive integer")
    _validate_reveal_stage(state.highest_reveal_stage)
    if state.snapshot.quotation_identity not in state.repetition_history:
        raise ValueError("repetition history must contain the current quotation identity")


def _state_payload(state: PersistentState) -> dict[str, object]:
    snapshot = state.snapshot
    return {
        "revision": state.revision,
        "highest_reveal_stage": state.highest_reveal_stage,
        "snapshot": {
            "quotation_text": snapshot.quotation_text,
            "quotation_identity": snapshot.quotation_identity,
            "font_identifier": snapshot.font_identifier,
            "presentation_metadata": _thaw_json(snapshot.presentation_metadata),
            "reveal_schedule": _thaw_json(snapshot.reveal_schedule),
            "layout": _thaw_json(snapshot.layout),
            "scheduling": {
                "display_date": snapshot.display_date.isoformat(),
                "timezone": snapshot.scheduling.timezone,
                "day_start": snapshot.scheduling.day_start,
            },
        },
        "repetition_history": sorted(state.repetition_history),
    }


def _encode_history_record(record: GlobalHistoryRecord) -> bytes:
    payload = {
        "revision": record.revision,
        "display_date": record.display_date.isoformat(),
        "selection_timestamp": record.selection_timestamp.isoformat().replace("+00:00", "Z"),
        "quotation_text": record.quotation_text,
        "quotation_identity": record.quotation_identity,
        "font_identifier": record.font_identifier,
    }
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _truncate_incomplete_history_tail(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r+b") as history_file:
        end = history_file.seek(0, os.SEEK_END)
        if end == 0:
            return
        history_file.seek(-1, os.SEEK_END)
        if history_file.read(1) == b"\n":
            return
        position = end
        while position:
            size = min(8192, position)
            position -= size
            history_file.seek(position)
            chunk = history_file.read(size)
            newline = chunk.rfind(b"\n")
            if newline >= 0:
                history_file.truncate(position + newline + 1)
                break
        else:
            history_file.truncate(0)
        history_file.flush()
        os.fsync(history_file.fileno())


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_document(state: PersistentState) -> bytes:
    payload = _state_payload(state)
    document = {
        "format_version": _FORMAT_VERSION,
        "state": payload,
        "sha256": hashlib.sha256(_canonical_json(payload)).hexdigest(),
    }
    return _canonical_json(document) + b"\n"


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_parent_directories(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        _sync_directory(directory.parent)

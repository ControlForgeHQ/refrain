"""Persistence and recovery of the selection's shared publication checkpoint.

The caller must first recover or commit authoritative operational state and
serialize all writers for that state directory. For a new selection, resolve QR
payloads from its accepted entry and configuration, then call ``initialize``.
For startup or after a failed write, call ``complete`` with freshly recovered
state. Only its successfully returned completed document may be used for
destination-specific preparation. Cache compatibility must include its QR and
canonical presentation, not merely the selection revision.
"""

from __future__ import annotations

import copy
import logging
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from .persistence import DailySnapshot, PersistentState
from .publication_metadata import (
    PublicationMetadataError,
    parse_publication_metadata,
    serialize_publication_metadata,
    validate_publication_metadata,
)

_LOG = logging.getLogger(__name__)
CanonicalResolver = Callable[[DailySnapshot, dict[str, object]], dict[str, object]]


class CheckpointError(Exception):
    """Checkpoint reading, association, or durable persistence failed."""

    def __init__(self, message: str, *, published: bool = False) -> None:
        super().__init__(message)
        self.published = published


def build_content_checkpoint(state: PersistentState, qr: Sequence[dict[str, object]]) -> dict[str, object]:
    """Construct the complete content form from committed state and resolved QR declarations."""
    if not isinstance(state, PersistentState):
        raise TypeError("state must be recovered committed PersistentState")
    if type(state.revision) is not int or state.revision < 1:
        raise ValueError("state revision must be positive")
    snapshot = state.snapshot
    stages = snapshot.resolved_reveal_stages
    stage = state.highest_reveal_stage
    if type(stage) is not int or stages is None or not 0 <= stage < len(stages):
        raise ValueError("state reveal stage must identify a committed resolved stage")
    visibility = stages[stage].visibility
    content: dict[str, object] = {
        "display_date": snapshot.display_date.isoformat(),
        "selection_revision": state.revision,
        "reveal_schedule": dict(snapshot.reveal_schedule),
        "reveal_stage": {
            "quotation": visibility.quotation,
            "source": visibility.source,
            "attribution": visibility.attribution,
        },
        "quotation": snapshot.quotation_text,
        "actions": [
            {"type": action.type, "visibility": list(action.visibility), "payload": action.payload}
            for action in snapshot.actions
        ],
        "qr": copy.deepcopy(list(qr)),
    }
    if snapshot.source is not None:
        content["source"] = snapshot.source
    if snapshot.attribution is not None:
        content["attribution"] = snapshot.attribution
    document: dict[str, object] = {"schema_version": 1, "content": content}
    validate_publication_metadata(document, stage="content")
    return document


def _associated(document: dict[str, object], state: PersistentState) -> bool:
    expected = build_content_checkpoint(state, [])
    actual_content = dict(document["content"])
    expected_content = dict(expected["content"])
    for field in ("qr", "reveal_stage"):
        actual_content.pop(field)
        expected_content.pop(field)
    return actual_content == expected_content


def validate_checkpoint(document: object, state: PersistentState, *, require_presentation: bool = False) -> None:
    """Validate form, selection association, and current committed visibility.

    Preparation and cache recovery can use this at their own boundaries. Unlike
    ``complete``, this function rejects rather than repairs stale visibility.
    """
    validate_publication_metadata(document, stage="presentation" if require_presentation else "checkpoint")
    if not _associated(document, state):
        raise CheckpointError("checkpoint does not match the committed selection")
    expected = build_content_checkpoint(state, [])
    if document["content"]["reveal_stage"] != expected["content"]["reveal_stage"]:
        raise CheckpointError("checkpoint visibility does not match committed reveal progress")


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_parent(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current == current.parent:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        _sync_directory(directory.parent)


class CheckpointStore:
    """Single-writer store for an absolute ``publication.json`` path."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("checkpoint path must be absolute")

    def invalidate(self) -> None:
        """Remove an orphan checkpoint before the initial state commitment.

        A failed removal or unconfirmed directory synchronization prevents the
        caller from committing initial state. The caller also invalidates cached
        images independently before that commitment.
        """
        removed = False
        try:
            try:
                self.path.unlink()
                removed = True
            except FileNotFoundError:
                pass
            if self.path.parent.exists():
                _sync_directory(self.path.parent)
        except OSError as error:
            raise CheckpointError(
                f"cannot invalidate orphan checkpoint {self.path}: {error}; do not commit initial state",
                published=removed,
            ) from error

    def initialize(self, state: PersistentState, qr: Sequence[dict[str, object]]) -> dict[str, object]:
        """Persist content immediately after a new selection is committed.

        ``qr`` contains already resolved publication-schema declarations. Never
        call this to reconstruct a lost checkpoint: use ``complete`` instead.
        """
        document = build_content_checkpoint(state, qr)
        self._write(document)
        return copy.deepcopy(document)

    def complete(self, state: PersistentState, resolver: CanonicalResolver) -> dict[str, object]:
        """Recover, reconcile and durably complete a committed selection's checkpoint.

        The resolver receives the immutable committed snapshot and a private copy
        of the content checkpoint, returning a complete presentation object. It
        is never invoked when a valid complete checkpoint can be recovered.
        A failed or ambiguous write raises, so callers must recover state and
        retry rather than beginning destination preparation.
        """
        expected = build_content_checkpoint(state, [])
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            document = None
        except OSError as error:
            raise CheckpointError(f"cannot read checkpoint {self.path}: {error}") from error
        else:
            try:
                document = parse_publication_metadata(data, stage="checkpoint")
                if not _associated(document, state):
                    document = None
            except (PublicationMetadataError, RecursionError):
                document = None

        if document is None:
            _LOG.warning(
                "Publication checkpoint %s is missing or invalid; original QR payloads cannot be recovered "
                "and appearance may differ. Reconstructing from committed state with no QR.",
                self.path,
            )
            document = expected
            self._write(document)
        else:
            # A previous replacement may have succeeded before directory fsync
            # failed. Confirm it before resolving or using its presentation.
            try:
                _sync_directory(self.path.parent)
            except OSError as error:
                raise CheckpointError(
                    f"cannot confirm checkpoint durability at {self.path}: {error}; reload before retrying",
                    published=True,
                ) from error
            content = document["content"]
            expected_visibility = expected["content"]["reveal_stage"]
            if content["reveal_stage"] != expected_visibility:
                content["reveal_stage"] = copy.deepcopy(expected_visibility)
                self._write(document)

        if "presentation" not in document:
            presentation = resolver(state.snapshot, copy.deepcopy(document))
            document["presentation"] = copy.deepcopy(presentation)
            self._write(document)
        return copy.deepcopy(document)

    def _write(self, document: dict[str, object]) -> None:
        serialized = serialize_publication_metadata(document, stage="checkpoint").encode("utf-8") + b"\n"
        temporary_path: Path | None = None
        published = False
        try:
            _create_parent(self.path.parent)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            published = True
            _sync_directory(self.path.parent)
        except OSError as error:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            outcome = "replacement occurred; reload before retrying" if published else "previous checkpoint remains"
            raise CheckpointError(
                f"cannot persist checkpoint {self.path}: {error}; {outcome}", published=published
            ) from error

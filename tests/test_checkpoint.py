from __future__ import annotations

import copy
import json
import logging
from datetime import date, datetime, timezone

import pytest

import refrain.checkpoint as checkpoint
from refrain.checkpoint import CheckpointError, CheckpointStore, build_content_checkpoint, validate_checkpoint
from refrain.content import ContentAction
from refrain.persistence import DailySnapshot, PersistentState, ResolvedRevealStage, SchedulingContext
from refrain.publication_metadata import PublicationMetadataError
from refrain.renderer import CompositionVisibility


@pytest.fixture
def state() -> PersistentState:
    snapshot = DailySnapshot(
        entry_id="example",
        quotation_text="  A thought.\n",
        quotation_identity="A thought.",
        source="Source",
        attribution="Author",
        presentation_style="centered",
        font=None,
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule={"quotation": "05:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 11, 18), "05:00"),
        actions=(ContentAction("play", ("external", "internal"), "opaque\n"),),
        resolved_reveal_stages=(
            ResolvedRevealStage(
                datetime(2026, 11, 18, 5, tzinfo=timezone.utc), CompositionVisibility(True, False, False)
            ),
            ResolvedRevealStage(
                datetime(2026, 11, 18, 12, tzinfo=timezone.utc), CompositionVisibility(True, True, False)
            ),
            ResolvedRevealStage(
                datetime(2026, 11, 18, 18, tzinfo=timezone.utc), CompositionVisibility(True, True, True)
            ),
        ),
    )
    return PersistentState(3, snapshot, frozenset({"A thought."}), 0)


@pytest.fixture
def presentation() -> dict[str, object]:
    return {
        "style": "centered",
        "background": "none",
        "decoration": "none",
        "fonts": {
            "bundle": "example",
            "faces": {"quotation": "regular", "source": "regular", "attribution": "regular"},
        },
        "colors": {"text": "black", "decoration": None},
        "font_size_range": {"minimum": 20, "maximum": 100},
        "insets": {"left": 1, "right": 1, "top": 1, "bottom": 1},
    }


@pytest.fixture
def qr() -> list[dict[str, object]]:
    return [
        {"visibility": ["external"], "payload": "public"},
        {"visibility": ["internal"], "payload": "private"},
    ]


def _later(state: PersistentState, stage: int) -> PersistentState:
    return PersistentState(state.revision, state.snapshot, state.repetition_history, stage)


def test_initialize_and_complete_are_separate_durable_forms(tmp_path, state, qr, presentation):
    store = CheckpointStore(tmp_path / "publication.json")
    content = store.initialize(state, qr)
    assert set(json.loads(store.path.read_bytes())) == {"schema_version", "content"}
    assert content["content"]["quotation"] == state.snapshot.quotation_text
    assert content["content"]["actions"] == [
        {"type": "play", "visibility": ["external", "internal"], "payload": "opaque\n"}
    ]
    qr[0]["payload"] = "changed"
    assert content["content"]["qr"][0]["payload"] == "public"

    def resolve(snapshot, supplied):
        assert snapshot == state.snapshot
        assert supplied == content
        supplied["content"]["qr"].clear()
        return presentation

    complete = store.complete(state, resolve)
    validate_checkpoint(complete, state, require_presentation=True)
    assert complete["content"]["qr"][0]["payload"] == "public"
    assert complete["presentation"] == presentation
    complete["presentation"]["style"] = "left-aligned"
    recovered = store.complete(state, lambda *_: pytest.fail("canonical choices must not be reselected"))
    assert recovered["presentation"] == presentation


def test_visibility_reconciles_without_losing_presentation_or_qr(tmp_path, state, qr, presentation):
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, qr)
    initial = store.complete(state, lambda *_: presentation)
    advanced = _later(state, 2)
    with pytest.raises(CheckpointError, match="visibility"):
        validate_checkpoint(initial, advanced, require_presentation=True)
    recovered = store.complete(advanced, lambda *_: pytest.fail("must preserve canonical choices"))
    assert recovered["content"]["reveal_stage"] == {"quotation": True, "source": True, "attribution": True}
    assert recovered["content"]["qr"] == qr
    assert recovered["presentation"] == presentation
    assert state.highest_reveal_stage == 0
    validate_checkpoint(recovered, advanced, require_presentation=True)


@pytest.mark.parametrize(
    "damage", ["missing", "syntax", "duplicate", "revision", "date", "quotation", "actions", "presentation", "form"]
)
def test_lost_or_invalid_checkpoint_rebuilds_empty_qr(tmp_path, state, qr, presentation, caplog, damage):
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, qr)
    valid = store.complete(state, lambda *_: presentation)
    if damage == "missing":
        store.path.unlink()
    elif damage == "syntax":
        store.path.write_text("{", encoding="utf-8")
    elif damage == "duplicate":
        store.path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    else:
        if damage == "revision":
            valid["content"]["selection_revision"] += 1
        elif damage == "date":
            valid["content"]["display_date"] = "2026-11-19"
        elif damage == "quotation":
            valid["content"]["quotation"] = "Different"
        elif damage == "actions":
            valid["content"]["actions"] = []
        elif damage == "presentation":
            valid["presentation"]["fonts"] = {}
        else:
            valid["publication"] = {}
        store.path.write_text(json.dumps(valid), encoding="utf-8")
    observed = []
    with caplog.at_level(logging.WARNING):
        result = store.complete(
            _later(state, 1), lambda snapshot, doc: observed.append(copy.deepcopy(doc)) or presentation
        )
    assert "QR payloads cannot be recovered" in caplog.text
    assert "appearance may differ" in caplog.text
    assert observed[0]["content"]["qr"] == []
    assert result["content"]["qr"] == []
    assert result["content"]["reveal_stage"]["source"] is True
    assert result["presentation"] == presentation
    validate_checkpoint(result, _later(state, 1), require_presentation=True)


def test_content_checkpoint_resumes_without_losing_qr(tmp_path, state, qr, presentation, caplog):
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, qr)
    result = store.complete(state, lambda *_: presentation)
    assert result["content"]["qr"] == qr
    assert not caplog.records


def test_failed_pre_replace_preserves_preceding_checkpoint_and_blocks_resolution(tmp_path, state, qr, monkeypatch):
    store = CheckpointStore(tmp_path / "publication.json")
    old = store.initialize(state, qr)

    def fail(*_):
        raise OSError("replacement blocked")

    monkeypatch.setattr(checkpoint.os, "replace", fail)
    with pytest.raises(CheckpointError) as raised:
        store.complete(_later(state, 1), lambda *_: pytest.fail("must not resolve before durable content"))
    assert not raised.value.published
    assert json.loads(store.path.read_bytes()) == old
    assert sorted(tmp_path.iterdir()) == [store.path]


def test_ambiguous_completed_write_requires_fresh_recovery(tmp_path, state, qr, presentation, monkeypatch):
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, qr)
    original_sync = checkpoint._sync_directory
    calls = []

    def fail_once(path):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("sync failed")
        original_sync(path)

    monkeypatch.setattr(checkpoint, "_sync_directory", fail_once)
    with pytest.raises(CheckpointError) as raised:
        store.complete(state, lambda *_: presentation)
    assert raised.value.published
    recovered = CheckpointStore(store.path).complete(state, lambda *_: pytest.fail("must reuse replaced presentation"))
    assert recovered["presentation"] == presentation
    assert len(calls) == 3


def test_unconfirmed_content_blocks_canonical_resolution(tmp_path, state, qr, monkeypatch):
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, qr)

    def fail(_):
        raise OSError("sync failed")

    monkeypatch.setattr(checkpoint, "_sync_directory", fail)
    with pytest.raises(CheckpointError) as raised:
        store.complete(state, lambda *_: pytest.fail("content durability must be confirmed before resolution"))
    assert raised.value.published


def test_invalidate_orphan_before_initial_commit(tmp_path, state, qr):
    store = CheckpointStore(tmp_path / "publication.json")
    store.initialize(state, qr)
    store.invalidate()
    assert not store.path.exists()
    store.invalidate()
    CheckpointStore(tmp_path / "absent" / "publication.json").invalidate()


def test_invalidate_refuses_failed_removal_or_sync(tmp_path, state, qr, monkeypatch):
    store = CheckpointStore(tmp_path / "publication.json")
    store.path.mkdir()
    with pytest.raises(CheckpointError, match="do not commit initial state") as raised:
        store.invalidate()
    assert not raised.value.published
    store.path.rmdir()
    store.initialize(state, qr)

    def fail(_):
        raise OSError("sync failed")

    monkeypatch.setattr(checkpoint, "_sync_directory", fail)
    with pytest.raises(CheckpointError) as raised:
        store.invalidate()
    assert raised.value.published
    assert not store.path.exists()


def test_bad_resolver_or_bad_input_never_publishes_completed_form(tmp_path, state, qr):
    store = CheckpointStore(tmp_path / "publication.json")
    content = store.initialize(state, qr)
    with pytest.raises(PublicationMetadataError):
        store.complete(state, lambda *_: {"style": "centered"})
    assert json.loads(store.path.read_bytes()) == content
    with pytest.raises(PublicationMetadataError):
        store.initialize(state, [{"payload": "", "visibility": ["external"]}])
    assert json.loads(store.path.read_bytes()) == content
    with pytest.raises(ValueError):
        build_content_checkpoint(_later(state, True), [])


def test_requires_absolute_path():
    with pytest.raises(ValueError, match="absolute"):
        CheckpointStore("publication.json")

from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import refrain.persistence as persistence
from refrain import (
    ContentEntry,
    DailySnapshot,
    EligibilityRule,
    PersistentStateStore,
    Quotation,
    QuotationCandidate,
    ResolvedFont,
    SchedulingContext,
    SelectionProposal,
    StateCommitError,
    StateRecoveryError,
    UnsupportedStateVersionError,
    build_eligible_quotation_pool,
    load_content_library,
    normalize_quotation,
    select_quotation,
)


def make_candidate(text: str) -> QuotationCandidate:
    quotation = Quotation(text=text, identity=normalize_quotation(text))
    entry = ContentEntry(
        id="entry",
        quotations=(quotation,),
        source="Resolved source",
        attribution="Resolved author",
        eligibility=(EligibilityRule(ordinary=True),),
    )
    return QuotationCandidate(quotation=quotation, entry=entry)


def make_proposal(
    text: str,
    history: frozenset[str] = frozenset(),
    *,
    base_revision: int = 0,
) -> SelectionProposal:
    candidate = make_candidate(text)
    return select_quotation(
        build_eligible_quotation_pool((candidate.entry,), date(2026, 10, 26)),
        history,
        random.Random(0),
        base_revision=base_revision,
    )


def make_snapshot(
    text: str,
    display_date: date = date(2026, 10, 26),
) -> DailySnapshot:
    return DailySnapshot(
        quotation_text=text,
        quotation_identity=normalize_quotation(text),
        font=ResolvedFont(identifier="test-font", data=b"resolved font contents"),
        presentation_metadata={"source": "Resolved source", "attribution": "Resolved author"},
        reveal_schedule={"quotation": "07:00", "source": "08:00", "attribution": "09:00"},
        layout={"quotation_region": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6}},
        scheduling=SchedulingContext(display_date, "Etc/UTC", "06:00"),
    )


def commit(store: PersistentStateStore, text: str, display_date: date = date(2026, 10, 26)):
    previous = store.load()
    history = frozenset() if previous is None else previous.repetition_history
    base_revision = 0 if previous is None else previous.revision
    proposal = make_proposal(text, history, base_revision=base_revision)
    return store.commit(proposal, make_snapshot(text, display_date))


def _write_document(path: Path, document: dict[str, object]) -> None:
    payload = document["state"]
    document["sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(document), encoding="utf-8")


def test_uninitialized_location_and_initial_commit_recover_in_new_instance(tmp_path: Path) -> None:
    state_path = tmp_path / "nested" / "state.json"
    store = PersistentStateStore(state_path)

    assert store.load() is None

    committed = commit(store, "First quotation.")
    recovered = PersistentStateStore(state_path).load()

    assert recovered == committed
    assert recovered.snapshot.quotation_text == "First quotation."
    assert recovered.snapshot.quotation_identity == "First quotation."
    assert recovered.snapshot.font.data == b"resolved font contents"
    assert recovered.global_history[0].sequence == 1
    assert recovered.global_history[0].font_identifier == "test-font"
    assert recovered.repetition_history == {"First quotation."}
    assert recovered.highest_reveal_stage == 0


def test_subsequent_commit_appends_history_and_persists_selective_reset(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    first = commit(store, "First quotation.")
    proposal = make_proposal(
        "Second quotation.",
        frozenset({"First quotation.", "Unrelated identity."}),
        base_revision=first.revision,
    )
    second = store.commit(proposal, make_snapshot("Second quotation.", date(2026, 10, 27)), initial_reveal_stage=1)

    assert second.revision == 2
    assert [record.quotation_text for record in second.global_history] == ["First quotation.", "Second quotation."]
    assert second.repetition_history == {"First quotation.", "Second quotation.", "Unrelated identity."}
    assert second.highest_reveal_stage == 1
    assert first.global_history == (first.global_history[0],)
    assert PersistentStateStore(store.path).load() == second

    reset = make_proposal(
        "First quotation.",
        frozenset({"First quotation.", "Unrelated identity."}),
        base_revision=second.revision,
    )
    third = store.commit(reset, make_snapshot("First quotation.", date(2026, 10, 28)))
    assert third.repetition_history == {"First quotation.", "Unrelated identity."}
    assert [record.sequence for record in third.global_history] == [1, 2, 3]


def test_exact_retry_is_idempotent_and_repeated_display_date_is_allowed(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    proposal = make_proposal("Committed.")
    snapshot = make_snapshot("Committed.")

    first = store.commit(proposal, snapshot)
    retry = store.commit(proposal, snapshot)

    assert retry == first
    assert len(retry.global_history) == 1

    repeated_date_proposal = make_proposal(
        "Replacement.",
        first.repetition_history,
        base_revision=first.revision,
    )
    repeated_date = store.commit(repeated_date_proposal, make_snapshot("Replacement."))
    assert repeated_date.revision == 2
    assert [record.display_date for record in repeated_date.global_history] == [
        date(2026, 10, 26),
        date(2026, 10, 26),
    ]
    assert repeated_date.global_history[0].sequence == 1
    assert repeated_date.global_history[1].sequence == 2
    assert store.commit(repeated_date_proposal, make_snapshot("Replacement.")) == repeated_date


def test_stale_proposal_cannot_overwrite_a_newer_repetition_history_generation(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    initial = commit(store, "Initial.")
    base_history = initial.repetition_history
    stale = make_proposal("Stale selection.", base_history, base_revision=initial.revision)
    current = make_proposal("Current selection.", base_history, base_revision=initial.revision)
    current_state = store.commit(current, make_snapshot("Current selection.", date(2026, 10, 27)))
    authoritative_bytes = store.path.read_bytes()

    with pytest.raises(StateCommitError, match="stale selection proposal"):
        store.commit(stale, make_snapshot("Stale selection.", date(2026, 10, 28)))

    assert store.path.read_bytes() == authoritative_bytes
    assert PersistentStateStore(store.path).load() == current_state


def test_commit_does_not_mutate_caller_owned_selection_history(tmp_path: Path) -> None:
    original_history = {"Unrelated identity."}
    candidate = make_candidate("Committed.")
    proposal = select_quotation(
        build_eligible_quotation_pool((candidate.entry,), date(2026, 10, 26)),
        original_history,
        random.Random(0),
        base_revision=0,
    )
    before_proposal = proposal

    PersistentStateStore(tmp_path / "state.json").commit(proposal, make_snapshot("Committed."))

    assert original_history == {"Unrelated identity."}
    assert proposal == before_proposal
    assert proposal.proposed_repetition_history == {"Committed.", "Unrelated identity."}


@pytest.mark.parametrize("failure_point", ["flush", "replace"])
def test_failures_before_publication_preserve_previous_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    previous = commit(store, "Previous.")
    proposal = make_proposal("Next.", previous.repetition_history, base_revision=previous.revision)

    if failure_point == "flush":
        monkeypatch.setattr(persistence.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("flush failed")))
    else:
        monkeypatch.setattr(persistence.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed")))

    with pytest.raises(StateCommitError) as error:
        store.commit(proposal, make_snapshot("Next.", date(2026, 10, 27)))

    assert not error.value.published
    assert PersistentStateStore(store.path).load() == previous
    assert proposal.selected_candidate.text == "Next."
    assert proposal.proposed_repetition_history == {"Previous.", "Next."}
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_failure_after_atomic_replace_reports_published_state_and_recovers_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    previous = commit(store, "Previous.")
    proposal = make_proposal("Next.", previous.repetition_history, base_revision=previous.revision)
    snapshot = make_snapshot("Next.", date(2026, 10, 27))
    monkeypatch.setattr(
        persistence, "_sync_directory", lambda _: (_ for _ in ()).throw(OSError("directory fsync failed"))
    )

    with pytest.raises(StateCommitError) as error:
        store.commit(proposal, snapshot)

    assert error.value.published
    recovered = PersistentStateStore(store.path).load()
    assert recovered.snapshot.quotation_text == "Next."
    assert [record.quotation_text for record in recovered.global_history] == ["Previous.", "Next."]
    assert previous.snapshot.quotation_text == "Previous."

    synced: list[Path] = []
    monkeypatch.setattr(persistence, "_sync_directory", lambda path: synced.append(path))
    assert store.commit(proposal, snapshot) == recovered
    assert synced == [store.path.parent]


def test_windows_directory_synchronization_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(persistence, "os", SimpleNamespace(name="nt"))

    persistence._sync_directory(tmp_path)


def test_recovery_does_not_require_original_content_or_configuration(tmp_path: Path) -> None:
    content_directory = tmp_path / "content"
    content_directory.mkdir()
    (content_directory / "entry.yaml").write_text(
        "id: sample\nsource: Old source\nattribution: Old author\nquotations:\n  - Original text.\n",
        encoding="utf-8",
    )
    entries = load_content_library(content_directory)
    pool = build_eligible_quotation_pool(entries, date(2026, 10, 26))
    proposal = select_quotation(pool, (), random.Random(0))
    candidate = proposal.selected_candidate
    snapshot = DailySnapshot(
        quotation_text=candidate.text,
        quotation_identity=candidate.identity,
        font=ResolvedFont(identifier="stable-font", data=b"font bytes captured at commitment"),
        presentation_metadata={"source": candidate.entry.source, "attribution": candidate.entry.attribution},
        reveal_schedule={"quotation": "07:00", "source": "08:00", "attribution": "09:00"},
        layout={"text_size": 42},
        scheduling=SchedulingContext(date(2026, 10, 26), "America/New_York", "06:00"),
    )
    state_path = tmp_path / "state.json"
    PersistentStateStore(state_path).commit(proposal, snapshot)

    (content_directory / "entry.yaml").unlink()
    recovered = PersistentStateStore(state_path).load()

    assert recovered.snapshot == snapshot
    assert recovered.snapshot.font.data == b"font bytes captured at commitment"
    assert recovered.snapshot.presentation_metadata == {"source": "Old source", "attribution": "Old author"}


@pytest.mark.parametrize("contents", [b"{", b"\xff", b""])
def test_malformed_or_truncated_state_is_not_treated_as_uninitialized(tmp_path: Path, contents: bytes) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_bytes(contents)

    with pytest.raises(StateRecoveryError, match="invalid persistent state"):
        PersistentStateStore(state_path).load()


def test_unsupported_version_is_reported_explicitly(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"format_version": 77, "state": {}, "sha256": ""}', encoding="utf-8")

    with pytest.raises(UnsupportedStateVersionError, match="unsupported persistent-state format version 77"):
        PersistentStateStore(state_path).load()


def test_missing_fields_and_inconsistent_history_are_rejected(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    commit(PersistentStateStore(state_path), "Persisted.")
    document = json.loads(state_path.read_text(encoding="utf-8"))
    del document["state"]["snapshot"]["layout"]
    _write_document(state_path, document)

    with pytest.raises(StateRecoveryError, match="snapshot: missing fields: layout"):
        PersistentStateStore(state_path).load()

    state_path.unlink()
    commit(PersistentStateStore(state_path), "Persisted.")
    document = json.loads(state_path.read_text(encoding="utf-8"))
    document["state"]["global_history"][0]["quotation_text"] = "Different."
    document["state"]["global_history"][0]["quotation_identity"] = "Different."
    _write_document(state_path, document)
    with pytest.raises(StateRecoveryError, match="does not match the latest global-history record"):
        PersistentStateStore(state_path).load()


def test_integrity_checksum_and_font_digest_are_validated(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    commit(PersistentStateStore(state_path), "Persisted.")
    document = json.loads(state_path.read_text(encoding="utf-8"))
    document["state"]["snapshot"]["font"]["data"] = "dGFtcGVyZWQ="
    _write_document(state_path, document)

    with pytest.raises(StateRecoveryError, match="font data checksum"):
        PersistentStateStore(state_path).load()

    state_path.write_text('{"format_version": 2, "state": {}, "sha256": "bad"}', encoding="utf-8")
    with pytest.raises(StateRecoveryError, match="checksum"):
        PersistentStateStore(state_path).load()


def test_store_requires_an_absolute_configured_path() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        PersistentStateStore("relative/state.json")


@pytest.mark.parametrize("stages", [(1,), (2,), (1, 2, 3)])
def test_reveal_progress_advances_without_changing_selection(tmp_path: Path, stages: tuple[int, ...]) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    original = commit(store, "Committed.")
    original_payload = json.loads(store.path.read_bytes())["state"]

    for stage in stages:
        advanced = store.advance_reveal_progress(original.revision, stage)
        assert advanced.highest_reveal_stage == stage
        assert advanced.snapshot == original.snapshot
        assert advanced.revision == original.revision
        assert advanced.global_history == original.global_history
        assert advanced.repetition_history == original.repetition_history
        assert PersistentStateStore(store.path).load() == advanced
        payload = json.loads(store.path.read_bytes())["state"]
        assert payload.pop("highest_reveal_stage") == stage
        assert payload == {key: value for key, value in original_payload.items() if key != "highest_reveal_stage"}

    assert original.highest_reveal_stage == 0


@pytest.mark.parametrize("requested_stage", [0, 1, 2])
def test_same_or_earlier_reveal_stage_does_not_rewrite_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested_stage: int
) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    committed = commit(store, "Committed.")
    advanced = store.advance_reveal_progress(committed.revision, 2)
    contents = store.path.read_bytes()
    stat = store.path.stat()

    def unexpected_publication(*_: object) -> None:
        pytest.fail("idempotent reveal progression must not publish state")

    monkeypatch.setattr(store, "_publish", unexpected_publication)
    assert store.advance_reveal_progress(committed.revision, requested_stage) == advanced
    assert store.path.read_bytes() == contents
    assert store.path.stat().st_mtime_ns == stat.st_mtime_ns
    assert store.path.stat().st_ino == stat.st_ino


def test_reveal_progress_restart_and_new_selection_integration(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    first = commit(store, "First.")
    store.advance_reveal_progress(first.revision, 1)
    store.advance_reveal_progress(first.revision, 2)

    restarted = PersistentStateStore(store.path)
    recovered = restarted.load()
    assert recovered.highest_reveal_stage == 2
    assert recovered.snapshot == first.snapshot
    assert recovered.revision == first.revision
    assert recovered.global_history == first.global_history
    assert recovered.repetition_history == first.repetition_history

    second = commit(restarted, "Second.", date(2026, 10, 27))
    assert second.highest_reveal_stage == 0
    assert second.revision == first.revision + 1
    contents = store.path.read_bytes()
    for stage in (0, 1, 3):
        with pytest.raises(StateCommitError, match="stale reveal-progress update"):
            store.advance_reveal_progress(first.revision, stage)
        assert store.path.read_bytes() == contents
        assert PersistentStateStore(store.path).load() == second
    assert restarted.advance_reveal_progress(second.revision, 1).highest_reveal_stage == 1


def test_selection_retry_preserves_subsequent_reveal_progress(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    proposal = make_proposal("Committed.")
    snapshot = make_snapshot("Committed.")
    first = store.commit(proposal, snapshot, initial_reveal_stage=1)
    advanced = store.advance_reveal_progress(first.revision, 2)
    contents = store.path.read_bytes()

    assert store.commit(proposal, snapshot, initial_reveal_stage=1) == advanced
    assert store.path.read_bytes() == contents


def test_uninitialized_state_cannot_accept_reveal_progress(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "missing" / "state.json")
    with pytest.raises(StateCommitError, match="without a committed selection"):
        store.advance_reveal_progress(1, 1)
    assert store.load() is None
    assert not store.path.parent.exists()


@pytest.mark.parametrize("stage", [-1, 1.5, "1", True, False, None, [], {}])
def test_invalid_reveal_stages_are_rejected_without_changing_state(tmp_path: Path, stage: object) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    committed = commit(store, "Committed.")
    contents = store.path.read_bytes()
    with pytest.raises(ValueError, match="highest_reveal_stage must be a nonnegative integer"):
        store.advance_reveal_progress(committed.revision, stage)
    proposal = make_proposal("Next.", committed.repetition_history, base_revision=committed.revision)
    with pytest.raises(ValueError, match="highest_reveal_stage must be a nonnegative integer"):
        store.commit(proposal, make_snapshot("Next."), initial_reveal_stage=stage)
    assert store.path.read_bytes() == contents


@pytest.mark.parametrize("revision", [0, -1, 1.0, "1", True, None])
def test_invalid_reveal_generation_is_rejected(tmp_path: Path, revision: object) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    commit(store, "Committed.")
    contents = store.path.read_bytes()
    with pytest.raises(StateCommitError, match="expected_revision must be a positive integer"):
        store.advance_reveal_progress(revision, 1)
    assert store.path.read_bytes() == contents


@pytest.mark.parametrize("failure_point", ["flush", "replace", "directory_sync"])
def test_interrupted_reveal_advancement_recovers_complete_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    committed = commit(store, "Committed.")
    previous = store.advance_reveal_progress(committed.revision, 1)
    original_payload = json.loads(store.path.read_bytes())["state"]

    def fail(*_: object) -> None:
        raise OSError("injected failure")

    with monkeypatch.context() as patch:
        if failure_point == "flush":
            patch.setattr(persistence.os, "fsync", fail)
        elif failure_point == "replace":
            patch.setattr(persistence.os, "replace", fail)
        else:
            patch.setattr(persistence, "_sync_directory", fail)
        with pytest.raises(StateCommitError) as error:
            store.advance_reveal_progress(previous.revision, 2)
        published = failure_point == "directory_sync"
        assert error.value.published is published
        recovered = PersistentStateStore(store.path).load()
        assert recovered.highest_reveal_stage == (2 if published else 1)
        payload = json.loads(store.path.read_bytes())["state"]
        payload["highest_reveal_stage"] = original_payload["highest_reveal_stage"]
        assert payload == original_payload
        assert not list(tmp_path.glob(".state.json.*.tmp"))
        if published:
            with pytest.raises(StateCommitError) as retry_error:
                store.advance_reveal_progress(previous.revision, 2)
            assert retry_error.value.published

    synced: list[Path] = []
    monkeypatch.setattr(persistence, "_sync_directory", lambda path: synced.append(path))
    retried = store.advance_reveal_progress(previous.revision, 2)
    assert retried.highest_reveal_stage == 2
    assert synced == [store.path.parent]
    assert PersistentStateStore(store.path).load() == retried


def test_version_one_snapshot_progress_is_rejected_explicitly(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    commit(store, "Committed.")
    document = json.loads(store.path.read_bytes())
    assert document["format_version"] == 2
    document["format_version"] = 1
    document["state"]["snapshot"]["highest_reveal_stage"] = document["state"].pop("highest_reveal_stage")
    _write_document(store.path, document)
    contents = store.path.read_bytes()

    with pytest.raises(UnsupportedStateVersionError, match="format version 1"):
        store.load()
    with pytest.raises(UnsupportedStateVersionError, match="format version 1"):
        store.advance_reveal_progress(1, 1)
    assert store.path.read_bytes() == contents


@pytest.mark.parametrize("stage", [-1, True, "1", None])
def test_invalid_persisted_reveal_progress_is_not_recovered(tmp_path: Path, stage: object) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    commit(store, "Committed.")
    document = json.loads(store.path.read_bytes())
    document["state"]["highest_reveal_stage"] = stage
    _write_document(store.path, document)
    with pytest.raises(StateRecoveryError, match="highest_reveal_stage must be a nonnegative integer"):
        store.load()

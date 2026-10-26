from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from pathlib import Path

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


def make_proposal(text: str, history: frozenset[str] = frozenset()) -> SelectionProposal:
    candidate = make_candidate(text)
    return select_quotation(
        build_eligible_quotation_pool((candidate.entry,), date(2026, 10, 26)),
        history,
        random.Random(0),
    )


def make_snapshot(
    text: str,
    display_date: date = date(2026, 10, 26),
    *,
    stage: int = 0,
) -> DailySnapshot:
    return DailySnapshot(
        quotation_text=text,
        quotation_identity=normalize_quotation(text),
        font=ResolvedFont(identifier="test-font", data=b"resolved font contents"),
        presentation_metadata={"source": "Resolved source", "attribution": "Resolved author"},
        reveal_schedule={"quotation": "07:00", "source": "08:00", "attribution": "09:00"},
        layout={"quotation_region": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.6}},
        scheduling=SchedulingContext(display_date, "Etc/UTC", "06:00"),
        highest_reveal_stage=stage,
    )


def commit(store: PersistentStateStore, text: str, display_date: date = date(2026, 10, 26)):
    proposal = make_proposal(text)
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
    assert recovered.snapshot.highest_reveal_stage == 0


def test_subsequent_commit_appends_history_and_persists_selective_reset(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    first = commit(store, "First quotation.")
    proposal = make_proposal("Second quotation.", frozenset({"First quotation.", "Unrelated identity."}))
    second = store.commit(proposal, make_snapshot("Second quotation.", date(2026, 10, 27), stage=1))

    assert second.revision == 2
    assert [record.quotation_text for record in second.global_history] == ["First quotation.", "Second quotation."]
    assert second.repetition_history == {"First quotation.", "Second quotation.", "Unrelated identity."}
    assert second.snapshot.highest_reveal_stage == 1
    assert first.global_history == (first.global_history[0],)
    assert PersistentStateStore(store.path).load() == second

    reset = make_proposal("First quotation.", frozenset({"First quotation.", "Unrelated identity."}))
    third = store.commit(reset, make_snapshot("First quotation.", date(2026, 10, 28)))
    assert third.repetition_history == {"First quotation.", "Unrelated identity."}
    assert [record.sequence for record in third.global_history] == [1, 2, 3]


def test_exact_retry_is_idempotent_and_same_day_replacement_is_rejected(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    proposal = make_proposal("Committed.")
    snapshot = make_snapshot("Committed.")

    first = store.commit(proposal, snapshot)
    retry = store.commit(proposal, snapshot)

    assert retry == first
    assert len(retry.global_history) == 1
    with pytest.raises(StateCommitError, match="already committed"):
        store.commit(make_proposal("Replacement."), make_snapshot("Replacement."))


def test_commit_does_not_mutate_caller_owned_selection_history(tmp_path: Path) -> None:
    original_history = {"Unrelated identity."}
    candidate = make_candidate("Committed.")
    proposal = select_quotation(
        build_eligible_quotation_pool((candidate.entry,), date(2026, 10, 26)),
        original_history,
        random.Random(0),
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
    proposal = make_proposal("Next.")

    if failure_point == "flush":
        monkeypatch.setattr(persistence.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("flush failed")))
    else:
        monkeypatch.setattr(persistence.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed")))

    with pytest.raises(StateCommitError) as error:
        store.commit(proposal, make_snapshot("Next.", date(2026, 10, 27)))

    assert not error.value.published
    assert PersistentStateStore(store.path).load() == previous
    assert proposal.selected_candidate.text == "Next."
    assert proposal.proposed_repetition_history == {"Next."}
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_failure_after_atomic_replace_reports_published_state_and_recovers_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    previous = commit(store, "Previous.")
    monkeypatch.setattr(
        persistence, "_sync_directory", lambda _: (_ for _ in ()).throw(OSError("directory fsync failed"))
    )

    with pytest.raises(StateCommitError) as error:
        store.commit(make_proposal("Next."), make_snapshot("Next.", date(2026, 10, 27)))

    assert error.value.published
    recovered = PersistentStateStore(store.path).load()
    assert recovered.snapshot.quotation_text == "Next."
    assert [record.quotation_text for record in recovered.global_history] == ["Previous.", "Next."]
    assert previous.snapshot.quotation_text == "Previous."


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

    state_path.write_text('{"format_version": 1, "state": {}, "sha256": "bad"}', encoding="utf-8")
    with pytest.raises(StateRecoveryError, match="checksum"):
        PersistentStateStore(state_path).load()


def test_store_requires_an_absolute_configured_path() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        PersistentStateStore("relative/state.json")

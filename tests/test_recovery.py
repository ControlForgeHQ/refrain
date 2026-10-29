from __future__ import annotations

from dataclasses import replace
from datetime import date
from importlib.resources import files
from pathlib import Path

import pytest
from PIL import Image

import refrain.recovery as recovery
from refrain import (
    ArtifactAccessError,
    ArtifactValidationError,
    ArtifactWriteError,
    CompositionVisibility,
    ContentEntry,
    DailyImagePreparationError,
    DailySnapshot,
    EligibilityRule,
    FontResource,
    PersistentStateStore,
    PreparedImageArtifactStore,
    Quotation,
    QuotationCandidate,
    SchedulingContext,
    SelectionProposal,
    normalize_quotation,
    prepare_daily_images,
    recover_prepared_daily_images,
)

_STAGES = (
    CompositionVisibility(),
    CompositionVisibility(source=True),
    CompositionVisibility(source=True, attribution=True),
)
_FONT_REGISTRY = {
    "committed-font": FontResource(
        "committed-font",
        files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf"),
        bundled=True,
    )
}


@pytest.fixture
def committed_state(tmp_path: Path):
    text = "A committed quotation for recovery."
    snapshot = DailySnapshot(
        quotation_text=text,
        quotation_identity=normalize_quotation(text),
        font_identifier="committed-font",
        presentation_metadata={
            "source": "Committed source",
            "attribution": "Committed author",
            "presentation_style": "centered",
        },
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        layout={
            "image_size": (320, 240),
            "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
            "min_font_size": 12,
            "max_font_size": 32,
        },
        scheduling=SchedulingContext(date(2026, 10, 26), "Etc/UTC", "06:00"),
    )
    quotation = Quotation(text, normalize_quotation(text))
    entry = ContentEntry(
        id="entry",
        quotations=(quotation,),
        source="Committed source",
        attribution="Committed author",
        eligibility=(EligibilityRule(ordinary=True),),
    )
    candidate = QuotationCandidate(quotation=quotation, entry=entry)
    proposal = SelectionProposal(candidate, frozenset({quotation.identity}), False)
    state_path = tmp_path / "state.json"
    state = PersistentStateStore(state_path).commit(proposal, snapshot, initial_reveal_stage=1)
    return state, state_path


@pytest.fixture
def artifact_store(tmp_path: Path) -> PreparedImageArtifactStore:
    return PreparedImageArtifactStore(tmp_path / "prepared")


def _store_images(store: PreparedImageArtifactStore, state, stages=_STAGES):
    images = prepare_daily_images(state.snapshot, stages, _FONT_REGISTRY)
    try:
        return store.store(state.revision, state.snapshot, images)
    finally:
        for image in images:
            image.close()


def _assert_images_closed(images: tuple[Image.Image, ...]) -> None:
    for image in images:
        with pytest.raises(ValueError, match="closed"):
            image.getpixel((0, 0))


def test_reuses_complete_artifacts_without_preparing_or_writing(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, state_path = committed_state
    expected = _store_images(artifact_store, state)
    manifest_path = expected.directory / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    image_bytes_before = tuple(path.read_bytes() for path in expected.stage_paths)
    state_bytes_before = state_path.read_bytes()

    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: pytest.fail("unexpected rendering"))
    monkeypatch.setattr(PreparedImageArtifactStore, "store", lambda *_args, **_kwargs: pytest.fail("unexpected write"))
    result = recover_prepared_daily_images(
        state, PreparedImageArtifactStore(artifact_store.root), _STAGES, _FONT_REGISTRY
    )

    assert result == expected
    assert manifest_path.read_bytes() == manifest_before
    assert tuple(path.read_bytes() for path in result.stage_paths) == image_bytes_before
    assert state_path.read_bytes() == state_bytes_before
    assert PersistentStateStore(state_path).load() == state


def test_valid_artifacts_are_reused_after_font_resource_changes(
    committed_state, artifact_store, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, state_path = committed_state
    state_bytes_before = state_path.read_bytes()
    font_path = tmp_path / "registered.ttf"
    first_font = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
    changed_font = files("refrain").joinpath("assets", "fonts", "source-sans-3", "SourceSans3-Regular.ttf")
    font_path.write_bytes(first_font.read_bytes())
    registry = {"committed-font": FontResource("committed-font", font_path, bundled=False)}

    original = recover_prepared_daily_images(state, artifact_store, _STAGES, registry)
    font_path.write_bytes(changed_font.read_bytes())
    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_args: pytest.fail("unexpected regeneration"))
    recovered = recover_prepared_daily_images(state, artifact_store, _STAGES, registry)

    assert recovered == original
    assert state_path.read_bytes() == state_bytes_before


@pytest.mark.parametrize(
    "damage",
    [
        "interrupted",
        "missing-stage",
        "corrupted-stage",
        "truncated-stage",
        "missing-manifest",
        "invalid-manifest",
        "wrong-stage-count",
        "wrong-snapshot",
    ],
)
def test_regenerates_and_replaces_absent_or_invalid_artifacts(committed_state, artifact_store, damage: str) -> None:
    state, state_path = committed_state
    state_bytes_before = state_path.read_bytes()
    previous_payloads: tuple[Path, ...] = ()

    if damage == "interrupted":
        (artifact_store.root / f"revision-{state.revision}").mkdir(parents=True)
    else:
        artifact_snapshot = state.snapshot
        artifact_stages = _STAGES
        if damage == "wrong-snapshot":
            artifact_snapshot = replace(
                state.snapshot,
                quotation_text="Different committed text.",
                quotation_identity="Different committed text.",
            )
        if damage == "wrong-stage-count":
            artifact_stages = _STAGES[:2]
        artifact_state = replace(state, snapshot=artifact_snapshot)
        old_set = _store_images(artifact_store, artifact_state, artifact_stages)
        previous_payloads = tuple(old_set.directory.glob("images-*"))

        if damage == "missing-stage":
            old_set.stage_paths[1].unlink()
        elif damage == "corrupted-stage":
            old_set.stage_paths[1].write_bytes(b"not a PNG")
        elif damage == "truncated-stage":
            old_set.stage_paths[1].write_bytes(old_set.stage_paths[1].read_bytes()[:45])
        elif damage == "missing-manifest":
            (old_set.directory / "manifest.json").unlink()
        elif damage == "invalid-manifest":
            (old_set.directory / "manifest.json").write_bytes(b"{")

    result = recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)
    reloaded = PreparedImageArtifactStore(artifact_store.root).load(
        state.revision, state.snapshot, stage_count=len(_STAGES)
    )

    assert result.revision == state.revision
    assert reloaded == result
    assert len(result.stage_paths) == len(_STAGES)
    assert all(path.is_file() for path in result.stage_paths)
    assert all(path.name == f"stage-{index}.png" for index, path in enumerate(result.stage_paths))
    expected_images = prepare_daily_images(state.snapshot, _STAGES, _FONT_REGISTRY)
    try:
        for index, expected in enumerate(expected_images):
            with result.load_stage(index) as image:
                assert image.size == (320, 240)
                assert image.mode == "RGB"
                assert image.tobytes() == expected.tobytes()
    finally:
        for image in expected_images:
            image.close()
    if previous_payloads:
        assert all(path.exists() for path in previous_payloads)
    assert state_path.read_bytes() == state_bytes_before
    assert PersistentStateStore(state_path).load() == state


def test_repeated_recovery_uses_reloaded_artifacts_without_rewriting(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = committed_state
    first = recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)
    manifest = (first.directory / "manifest.json").read_bytes()

    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: pytest.fail("unexpected rendering"))
    second = recover_prepared_daily_images(
        state, PreparedImageArtifactStore(artifact_store.root), _STAGES, _FONT_REGISTRY
    )

    assert second == first
    assert (second.directory / "manifest.json").read_bytes() == manifest


@pytest.mark.parametrize(
    "stages",
    [
        (CompositionVisibility(), CompositionVisibility(source=True), CompositionVisibility()),
        (CompositionVisibility(), CompositionVisibility(quotation=False)),
        (CompositionVisibility(), CompositionVisibility(source=True)),
    ],
)
def test_rejects_inconsistent_stage_definitions_before_reuse(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch, stages
) -> None:
    state, _ = committed_state
    _store_images(artifact_store, state)
    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: pytest.fail("unexpected rendering"))

    with pytest.raises(DailyImagePreparationError):
        recover_prepared_daily_images(state, artifact_store, stages, _FONT_REGISTRY)


def test_rejects_reveals_for_fields_absent_from_snapshot(committed_state, artifact_store) -> None:
    state, _ = committed_state
    state_without_source = replace(
        state,
        snapshot=replace(
            state.snapshot,
            presentation_metadata={"attribution": "Committed author", "presentation_style": "centered"},
        ),
    )

    with pytest.raises(DailyImagePreparationError, match="absent"):
        recover_prepared_daily_images(
            state_without_source,
            artifact_store,
            (CompositionVisibility(), CompositionVisibility(source=True)),
            _FONT_REGISTRY,
        )


def test_rendering_failure_preserves_committed_state_and_storage(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, state_path = committed_state
    before = state_path.read_bytes()
    error = DailyImagePreparationError("injected rendering failure")
    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: (_ for _ in ()).throw(error))

    with pytest.raises(DailyImagePreparationError) as raised:
        recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)

    assert raised.value is error
    assert not artifact_store.root.exists()
    assert state_path.read_bytes() == before
    assert PersistentStateStore(state_path).load() == state


@pytest.mark.parametrize("published", [False, True])
def test_storage_failure_is_preserved_and_closes_generated_images(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch, published: bool
) -> None:
    state, state_path = committed_state
    before = state_path.read_bytes()
    images = tuple(Image.new("RGB", (320, 240), color) for color in ("white", "gray", "black"))
    error = ArtifactWriteError("injected storage failure", published=published)
    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: images)
    monkeypatch.setattr(artifact_store, "store", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(ArtifactWriteError) as raised:
        recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)

    assert raised.value is error
    assert raised.value.published is published
    _assert_images_closed(images)
    assert state_path.read_bytes() == before
    assert PersistentStateStore(state_path).load() == state


def test_successful_storage_closes_images_and_is_reusable_after_restart(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, state_path = committed_state
    before = state_path.read_bytes()
    images = tuple(Image.new("RGB", (320, 240), color) for color in ("white", "gray", "black"))
    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: images)

    result = recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)
    reloaded = PreparedImageArtifactStore(artifact_store.root).load(
        state.revision, state.snapshot, stage_count=len(_STAGES)
    )

    assert reloaded == result
    _assert_images_closed(images)
    assert state_path.read_bytes() == before
    assert PersistentStateStore(state_path).load() == state


def test_artifact_root_access_failure_is_not_treated_as_a_cache_miss(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = committed_state

    def deny_access():
        raise PermissionError("injected permission failure")

    monkeypatch.setattr(artifact_store, "_check_root", deny_access)
    monkeypatch.setattr(recovery, "prepare_daily_images", lambda *_: pytest.fail("unexpected rendering"))

    with pytest.raises(ArtifactAccessError, match="injected permission failure"):
        recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)


def test_artifact_validation_error_triggers_regeneration_but_access_error_does_not(
    committed_state, artifact_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = committed_state
    error = ArtifactValidationError("damaged artifact")
    monkeypatch.setattr(artifact_store, "load", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    prepared = []

    def prepare(snapshot, stages, font_registry):
        prepared.append(tuple(stages))
        return tuple(Image.new("RGB", (320, 240), "white") for _ in stages)

    monkeypatch.setattr(recovery, "prepare_daily_images", prepare)
    result = recover_prepared_daily_images(state, artifact_store, _STAGES, _FONT_REGISTRY)

    assert result.revision == state.revision
    assert prepared == [_STAGES]

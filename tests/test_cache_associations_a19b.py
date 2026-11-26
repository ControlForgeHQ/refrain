from __future__ import annotations

import copy
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
from PIL import Image

import refrain.artifacts as artifacts
from refrain.artifacts import ArtifactCleanupError, ArtifactWriteError, PreparedImageArtifactStore
from refrain.checkpoint import build_content_checkpoint
from refrain.config import (
    ApplicationConfiguration,
    DestinationPresentation,
    PreparedImageVariantKey,
    PresentationInsets,
    RevealSchedule,
)
from refrain.geometry import ResolvedOutputSpecification
from refrain.persistence import DailySnapshot, PersistentState, ResolvedRevealStage, SchedulingContext
from refrain.recovery import recover_prepared_daily_images
from refrain.renderer import CompositionVisibility


@pytest.fixture
def context():
    stages = (CompositionVisibility(True, False, False), CompositionVisibility(True, True, False))
    snapshot = DailySnapshot(
        entry_id="test",
        quotation_text="Thought",
        quotation_identity="Thought",
        source="Source",
        attribution=None,
        presentation_style="centered",
        font=None,
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule={"quotation": "05:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 11, 18), "05:00"),
        resolved_reveal_stages=(
            ResolvedRevealStage(datetime(2026, 11, 18, 5, tzinfo=timezone.utc), stages[0]),
            ResolvedRevealStage(datetime(2026, 11, 18, 12, tzinfo=timezone.utc), stages[1]),
        ),
    )
    state = PersistentState(1, snapshot, frozenset({"Thought"}), 0)
    declarations = [
        {"visibility": ["external"], "payload": "same"},
        {"visibility": ["internal"], "payload": "same"},
    ]
    checkpoint = build_content_checkpoint(state, declarations)
    checkpoint["presentation"] = {
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
    return state, stages, checkpoint, declarations


def _associations(state, stages, checkpoint, specification, declaration, effective=None):
    return tuple(
        {
            "selection_revision": state.revision,
            "visibility": {"quotation": stage.quotation, "source": stage.source, "attribution": stage.attribution},
            "effective_presentation": copy.deepcopy(effective or checkpoint["presentation"]),
            "rendered_qr": copy.deepcopy(declaration),
            "output_specification": {
                "aspect_ratio": specification.aspect_ratio,
                "requested_output_size": list(specification.requested_output_size),
            },
        }
        for stage in stages
    )


def test_cache_associates_payload_canonical_presentation_and_effective_values(tmp_path, context):
    state, stages, checkpoint, declarations = context
    spec = ResolvedOutputSpecification("4:3", (32, 24))
    key = PreparedImageVariantKey(spec, DestinationPresentation(), qr_payload="same")
    store = PreparedImageArtifactStore(tmp_path / "cache")
    effective = copy.deepcopy(checkpoint["presentation"])
    effective["fonts"]["bundle"] = "fallback"
    images = [Image.new("RGB", spec.requested_output_size, color) for color in ("white", "black")]
    try:
        store.store(
            state.revision,
            stages,
            {key: images},
            {key: _associations(state, stages, checkpoint, spec, declarations[0], effective)},
            snapshot=state.snapshot,
            checkpoint=checkpoint,
            qr_declaration=declarations[0],
        )
    finally:
        for image in images:
            image.close()
    cached = store.load(
        state.revision, stages, (key,), snapshot=state.snapshot, checkpoint=checkpoint, qr_declaration=declarations[1]
    )
    assert cached is not None
    association = cached.variant_for(key).load_association(1)
    assert association["effective_presentation"] == effective
    assert association["rendered_qr"] == declarations[1]
    advanced = copy.deepcopy(checkpoint)
    advanced["content"]["reveal_stage"]["source"] = True
    assert cached.association_matches(advanced)
    changed = copy.deepcopy(checkpoint)
    changed["presentation"]["style"] = "left-aligned"
    assert not cached.association_matches(changed)
    assert (
        store.load(
            state.revision, stages, (key,), snapshot=state.snapshot, checkpoint=changed, qr_declaration=declarations[1]
        )
        is None
    )
    changed = copy.deepcopy(checkpoint)
    changed["content"]["qr"][0]["payload"] = "other"
    assert not cached.association_matches(changed)
    other_key = PreparedImageVariantKey(spec, DestinationPresentation(), qr_payload="other")
    assert (
        store.load(
            state.revision,
            stages,
            (other_key,),
            snapshot=state.snapshot,
            checkpoint=changed,
            qr_declaration=changed["content"]["qr"][0],
        )
        is None
    )
    assert (
        store.load(state.revision, stages, (spec,), snapshot=state.snapshot, checkpoint=checkpoint, qr_declaration=None)
        is None
    )


def test_independent_sets_survive_damage_and_preserve_suppression(tmp_path, context):
    state, stages, checkpoint, declarations = context
    first = ResolvedOutputSpecification("4:3", (32, 24))
    second = ResolvedOutputSpecification("4:3", (40, 30))
    store = PreparedImageArtifactStore(tmp_path / "cache")
    images = {spec: [Image.new("RGB", spec.requested_output_size) for _ in stages] for spec in (first, second)}
    try:
        sets = store.store(
            state.revision,
            stages,
            images,
            {spec: _associations(state, stages, checkpoint, spec, None) for spec in images},
            snapshot=state.snapshot,
            checkpoint=checkpoint,
            qr_declaration=None,
        )
    finally:
        for group in images.values():
            for image in group:
                image.close()
    sets.variant_for(first).stage_paths[0].write_bytes(b"broken")
    valid, missing = store.load_groups(
        state.revision, stages, (first, second), snapshot=state.snapshot, checkpoint=checkpoint, qr_declaration=None
    )
    assert missing == (first,)
    assert valid.variant_for(second).load_association(0)["rendered_qr"] is None


def test_invalidate_all_rejects_unowned_and_linked_entries(tmp_path, context):
    store = PreparedImageArtifactStore(tmp_path / "cache")
    store.root.mkdir()
    (store.root / "unknown").write_text("preserve")
    with pytest.raises(ArtifactCleanupError):
        store.invalidate_all()
    assert (store.root / "unknown").read_text() == "preserve"
    (store.root / "unknown").unlink()
    target = tmp_path / "target"
    target.mkdir()
    try:
        (store.root / "revision-1").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(ArtifactCleanupError):
        store.invalidate_all()
    assert target.is_dir()


def test_suppressed_qr_is_not_shared_with_rendered_qr_and_invalidation_succeeds(tmp_path, context):
    state, stages, checkpoint, declarations = context
    spec = ResolvedOutputSpecification("4:3", (32, 24))
    presentation = DestinationPresentation(qr_enabled=False)
    key = PreparedImageVariantKey(spec, presentation)
    store = PreparedImageArtifactStore(tmp_path / "cache")
    images = [Image.new("RGB", spec.requested_output_size) for _ in stages]
    try:
        store.store(
            state.revision,
            stages,
            {key: images},
            {key: _associations(state, stages, checkpoint, spec, None)},
            snapshot=state.snapshot,
            checkpoint=checkpoint,
            qr_declaration=declarations[0],
        )
    finally:
        for image in images:
            image.close()
    result = store.load(
        state.revision, stages, (key,), snapshot=state.snapshot, checkpoint=checkpoint, qr_declaration=declarations[1]
    )
    assert result.variant_for(key).load_association(0)["rendered_qr"] is None
    rendered = PreparedImageVariantKey(spec, DestinationPresentation(), qr_payload="same")
    assert (
        store.load(
            state.revision,
            stages,
            (rendered,),
            snapshot=state.snapshot,
            checkpoint=checkpoint,
            qr_declaration=declarations[0],
        )
        is None
    )
    store.invalidate_all()
    assert not tuple(store.root.iterdir())


def test_failed_replacement_preserves_previously_committed_set(tmp_path, context, monkeypatch):
    state, stages, checkpoint, _ = context
    spec = ResolvedOutputSpecification("4:3", (32, 24))
    store = PreparedImageArtifactStore(tmp_path / "cache")
    association = _associations(state, stages, checkpoint, spec, None)

    def store_color(color):
        images = [Image.new("RGB", spec.requested_output_size, color) for _ in stages]
        try:
            return store.store(
                state.revision,
                stages,
                {spec: images},
                {spec: association},
                snapshot=state.snapshot,
                checkpoint=checkpoint,
                qr_declaration=None,
            )
        finally:
            for image in images:
                image.close()

    store_color("white")
    replace = artifacts.os.replace

    def fail_manifest(source, destination):
        if Path(destination).name == "manifest.json":
            raise OSError("injected replacement failure")
        replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", fail_manifest)
    with pytest.raises(ArtifactWriteError) as error:
        store_color("black")
    assert not error.value.published
    cached = store.load(
        state.revision, stages, (spec,), snapshot=state.snapshot, checkpoint=checkpoint, qr_declaration=None
    )
    with cached.load_stage(spec, 0) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_cleanup_preserves_distinct_qr_payloads_for_same_output(tmp_path, context):
    state, stages, checkpoint, declarations = context
    declarations[1]["payload"] = "different"
    checkpoint["content"]["qr"] = copy.deepcopy(declarations)
    spec = ResolvedOutputSpecification("4:3", (32, 24))
    presentation = DestinationPresentation()
    keys = tuple(PreparedImageVariantKey(spec, presentation, qr_payload=item["payload"]) for item in declarations)
    store = PreparedImageArtifactStore(tmp_path / "cache")
    for key, declaration in zip(keys, declarations, strict=True):
        images = [Image.new("RGB", spec.requested_output_size) for _ in stages]
        try:
            store.store(
                state.revision,
                stages,
                {key: images},
                {key: _associations(state, stages, checkpoint, spec, declaration)},
                snapshot=state.snapshot,
                checkpoint=checkpoint,
                qr_declaration=declaration,
            )
        finally:
            for image in images:
                image.close()
    store.cleanup(state.revision, keys, checkpoint=checkpoint)
    for key, declaration in zip(keys, declarations, strict=True):
        result = store.load(
            state.revision,
            stages,
            (key,),
            snapshot=state.snapshot,
            checkpoint=checkpoint,
            qr_declaration=declaration,
        )
        assert result is not None
        assert result.variant_for(key).load_association(0)["rendered_qr"] == declaration
    with pytest.raises(ValueError, match="duplicates"):
        store.cleanup(state.revision, (keys[0], keys[0]), checkpoint=checkpoint)
    store.cleanup(state.revision, keys)


def test_recovery_reuses_cache_without_preparation_and_rejects_changed_checkpoint(tmp_path, context, monkeypatch):
    state, stages, checkpoint, declarations = context
    spec = ResolvedOutputSpecification("4:3", (32, 24))
    key = PreparedImageVariantKey(spec, DestinationPresentation(), qr_payload="same")
    store = PreparedImageArtifactStore(tmp_path / "cache")
    configuration = ApplicationConfiguration(
        file=Path("/config"),
        display_backends=(),
        day_start=time(5),
        content_directory=Path("/content"),
        reveal=RevealSchedule(time(12), time(18)),
        presentation_insets=PresentationInsets(1, 1, 1, 1),
        fonts={},
        default_fonts=(),
        min_font_size=20,
        max_font_size=100,
    )
    calls = []

    def prepare(snapshot, supplied_stages, config, keys, **kwargs):
        calls.append(keys)
        assert kwargs["canonical_presentation"] == checkpoint["presentation"]
        kwargs["on_metadata"](key, _associations(state, stages, checkpoint, spec, kwargs["qr_declaration"]))
        for _ in stages:
            image = Image.new("RGB", spec.requested_output_size)
            try:
                kwargs["_on_stage"](key, image)
            finally:
                image.close()
        return {key: ()}

    monkeypatch.setattr("refrain.recovery.prepare_daily_images", prepare)
    result = recover_prepared_daily_images(
        state, store, stages, configuration, (key,), checkpoint=checkpoint, qr_declaration=declarations[0]
    )
    assert result.variant_for(key).load_association(0)["rendered_qr"] == declarations[0]
    monkeypatch.setattr("refrain.recovery.prepare_daily_images", lambda *a, **k: pytest.fail("unexpected regeneration"))
    recovered = recover_prepared_daily_images(
        state, store, stages, configuration, (key,), checkpoint=checkpoint, qr_declaration=declarations[1]
    )
    assert recovered.variant_for(key).load_association(0)["rendered_qr"] == declarations[1]
    assert len(calls) == 1
    invalid = copy.deepcopy(checkpoint)
    invalid["content"]["quotation"] = "Not the committed selection"
    with pytest.raises(Exception, match="committed selection"):
        recover_prepared_daily_images(
            state, store, stages, configuration, (key,), checkpoint=invalid, qr_declaration=declarations[0]
        )

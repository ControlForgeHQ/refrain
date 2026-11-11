from __future__ import annotations

import gc
import hashlib
import json
import os
import weakref
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

import refrain.artifacts as artifacts
from refrain import (
    ArtifactAccessError,
    ArtifactCleanupError,
    ArtifactValidationError,
    ArtifactWriteError,
    CompositionVisibility,
    ContentEntry,
    DailySnapshot,
    PersistentStateStore,
    PreparedImageArtifactSet,
    PreparedImageArtifactStore,
    Quotation,
    QuotationCandidate,
    ResolvedOutputSpecification,
    SchedulingContext,
    SelectionProposal,
)

_STAGES = (
    CompositionVisibility(),
    CompositionVisibility(source=True),
    CompositionVisibility(source=True, attribution=True),
)
_SPECIFICATION = ResolvedOutputSpecification("4:3", (32, 24))


def _store_one(store, revision, stages, images):
    return store.store(revision, stages, {_SPECIFICATION: images})


def _load_one(store, revision, stages):
    return store.load(revision, stages, (_SPECIFICATION,))


def _variant(artifact_set):
    return artifact_set.variant_for(_SPECIFICATION)


@pytest.fixture
def snapshot():
    return _STAGES


@pytest.fixture
def selected_snapshot() -> DailySnapshot:
    return DailySnapshot(
        entry_id="test-entry",
        quotation_text="A thought worth keeping.",
        quotation_identity="A thought worth keeping.",
        source="Collection",
        attribution="Author",
        presentation_style="centered",
        font="test",
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 10, 26), "06:00"),
    )


@pytest.fixture
def images():
    stages = tuple(Image.new("RGB", (32, 24), color) for color in ("white", "gray", "black"))
    yield stages
    for image in stages:
        image.close()


@pytest.fixture
def store(tmp_path: Path) -> PreparedImageArtifactStore:
    return PreparedImageArtifactStore(tmp_path / "derived" / "artifacts")


def rewrite_manifest(result: PreparedImageArtifactSet, mutate) -> None:
    path = result.directory / "manifest.json"
    document = json.loads(path.read_bytes())
    mutate(document["artifacts"])
    document["sha256"] = hashlib.sha256(
        json.dumps(
            document["artifacts"], ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("count", [1, 3])
def test_complete_sets_survive_restart_and_have_independently_readable_pngs(store, snapshot, images, count) -> None:
    result = _store_one(store, 1, snapshot[:count], images[:count])
    assert result.directory == store.root / "revision-1"
    stage_paths = _variant(result).stage_paths
    assert tuple(path.name for path in stage_paths) == tuple(f"stage-{i}.png" for i in range(count))
    metadata = json.loads((result.directory / "manifest.json").read_bytes())["artifacts"]
    assert set(metadata) == {"revision", "image_directory", "variants"}
    variant_metadata = metadata["variants"][0]
    assert set(variant_metadata) == {"aspect_ratio", "requested_output_size", "mode", "stages"}
    assert variant_metadata["aspect_ratio"] == _SPECIFICATION.aspect_ratio
    assert variant_metadata["requested_output_size"] == list(_SPECIFICATION.requested_output_size)
    assert variant_metadata["mode"] == "RGB"
    assert all(set(stage) == {"visibility", "sha256"} for stage in variant_metadata["stages"])
    for path, original in zip(stage_paths, images):
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == original.size
            assert image.mode == original.mode
            assert image.tobytes() == original.tobytes()
    reloaded = PreparedImageArtifactStore(store.root).load(1, snapshot[:count], (_SPECIFICATION,))
    assert reloaded == result
    with reloaded.load_stage(_SPECIFICATION, count - 1) as image:
        assert image.tobytes() == images[count - 1].tobytes()


def test_multiple_variants_keep_aspect_identity_and_validate_each_raster(store, snapshot, images) -> None:
    wide_specification = ResolvedOutputSpecification("16:9", (32, 24))
    with (
        Image.new("L", (32, 24), 40) as first,
        Image.new("L", (32, 24), 80) as second,
        Image.new("L", (32, 24), 120) as third,
    ):
        grayscale_images = (first.copy(), second.copy(), third.copy())
    try:
        result = store.store(
            1,
            snapshot,
            {_SPECIFICATION: images, wide_specification: grayscale_images},
        )
    finally:
        for image in grayscale_images:
            image.close()

    assert result.output_specifications == (wide_specification, _SPECIFICATION)
    assert result.variant_for(_SPECIFICATION).requested_output_size == wide_specification.requested_output_size
    assert result.variant_for(_SPECIFICATION).mode == "RGB"
    assert result.variant_for(wide_specification).mode == "L"
    assert result.variant_for(_SPECIFICATION).stage_paths != result.variant_for(wide_specification).stage_paths
    reloaded = store.load(1, snapshot, (wide_specification, _SPECIFICATION))
    assert reloaded == result
    with reloaded.load_stage(_SPECIFICATION, 1) as image:
        assert image.mode == "RGB" and image.tobytes() == images[1].tobytes()
    with reloaded.load_stage(wide_specification, 2) as image:
        assert image.mode == "L" and image.getpixel((0, 0)) == 120


def test_equivalent_specifications_are_deduplicated_and_expected_set_is_exact(store, snapshot, images) -> None:
    equivalent = ResolvedOutputSpecification("4:3", [32, 24])
    assert equivalent == _SPECIFICATION
    assert hash(equivalent) == hash(_SPECIFICATION)
    result = _store_one(store, 1, snapshot, images)

    with pytest.raises(ValueError, match="equivalent duplicates"):
        store.load(1, snapshot, (_SPECIFICATION, equivalent))
    with pytest.raises(ArtifactValidationError, match="exactly 2 output variants"):
        store.load(1, snapshot, (_SPECIFICATION, ResolvedOutputSpecification("16:9", (32, 24))))
    assert result.output_specifications == (_SPECIFICATION,)


def test_variant_stage_loading_does_not_open_other_stages_or_variants(store, snapshot, images, monkeypatch) -> None:
    other_specification = ResolvedOutputSpecification("16:9", (32, 24))
    with Image.new("RGB", (32, 24), "purple") as other_image:
        other_images = tuple(other_image.copy() for _ in snapshot)
    try:
        result = store.store(1, snapshot, {_SPECIFICATION: images, other_specification: other_images})
    finally:
        for image in other_images:
            image.close()
    opened = []
    original_open = Image.open

    def capture_open(source, *args, **kwargs):
        opened.append(Path(source.name))
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(artifacts.Image, "open", capture_open)
    with result.load_stage(other_specification, 1) as image:
        assert image.getpixel((0, 0)) == (128, 0, 128)
    expected_path = result.variant_for(other_specification).stage_paths[1]
    assert opened == [expected_path, expected_path]


def test_missing_unexpected_or_corrupt_variant_invalidates_the_complete_set(store, snapshot, images) -> None:
    other_specification = ResolvedOutputSpecification("16:9", (32, 24))
    with Image.new("RGB", (32, 24), "navy") as other_image:
        other_images = tuple(other_image.copy() for _ in snapshot)
    try:
        result = store.store(1, snapshot, {_SPECIFICATION: images, other_specification: other_images})
    finally:
        for image in other_images:
            image.close()

    with pytest.raises(ArtifactValidationError, match="exactly 1 output variants"):
        store.load(1, snapshot, (_SPECIFICATION,))
    changed_aspect = ResolvedOutputSpecification("5:3", (32, 24))
    with pytest.raises(ArtifactValidationError):
        store.load(1, snapshot, (_SPECIFICATION, changed_aspect))

    missing_stage = result.variant_for(other_specification).stage_paths[0]
    missing_stage_bytes = missing_stage.read_bytes()
    missing_stage.unlink()
    with pytest.raises(ArtifactValidationError, match="expected stages"):
        store.load(1, snapshot, (other_specification, _SPECIFICATION))
    missing_stage.write_bytes(missing_stage_bytes)

    corrupted = result.variant_for(other_specification).stage_paths[1]
    corrupted.write_bytes(b"damaged")
    with pytest.raises(ArtifactValidationError):
        store.load(1, snapshot, (other_specification, _SPECIFICATION))


def test_unexpected_variant_directory_invalidates_the_complete_set(store, snapshot, images) -> None:
    result = _store_one(store, 1, snapshot, images)
    payload = _variant(result).stage_paths[0].parent.parent
    unexpected = payload / "variant-5-3-32x24"
    unexpected.mkdir()
    with pytest.raises(ArtifactValidationError, match="exactly the expected output variants"):
        _load_one(store, 1, snapshot)


def test_requested_dimensions_are_validated_per_variant(store, snapshot, images) -> None:
    larger_specification = ResolvedOutputSpecification("16:9", (64, 36))
    with pytest.raises(ValueError, match="size \\(64, 36\\)"):
        store.store(1, snapshot, {larger_specification: images})
    larger_images = tuple(Image.new("RGB", (64, 36), "white") for _ in snapshot)
    try:
        result = store.store(1, snapshot, {_SPECIFICATION: images, larger_specification: larger_images})
    finally:
        for image in larger_images:
            image.close()
    path = result.variant_for(larger_specification).stage_paths[0]
    with Image.new("RGB", (32, 24), "white") as wrong_size:
        wrong_size.save(path)
    rewrite_manifest(
        result,
        lambda metadata: metadata["variants"][0]["stages"][0].update(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        ),
    )
    with pytest.raises(ArtifactValidationError, match="expected PNG size"):
        store.load(1, snapshot, (larger_specification, _SPECIFICATION))


def test_old_single_raster_manifest_format_is_not_reused(store, snapshot, images) -> None:
    result = _store_one(store, 1, snapshot, images)

    def replace_with_old_format(metadata):
        metadata.clear()
        metadata.update(
            revision=1,
            image_directory=_variant(result).stage_paths[0].parent.parent.name,
            image_size=[32, 24],
            mode="RGB",
            stages=[],
        )

    rewrite_manifest(result, replace_with_old_format)
    with pytest.raises(ArtifactValidationError, match="missing or unsupported"):
        _load_one(store, 1, snapshot)


@pytest.mark.parametrize("mode", ["1", "L", "LA", "RGB", "RGBA"])
def test_supported_modes_are_preserved_losslessly(store, snapshot, mode) -> None:
    with Image.new(mode, (32, 24)) as image:
        result = _store_one(store, 1, snapshot[:1], (image,))
        with result.load_stage(_SPECIFICATION, 0) as loaded:
            assert loaded.mode == mode
            assert loaded.tobytes() == image.tobytes()


def test_revisions_have_distinct_locations(store, snapshot, images) -> None:
    first = _store_one(store, 1, snapshot, images)
    second = _store_one(store, 2, snapshot, images)
    assert first.directory != second.directory
    assert _load_one(store, 1, snapshot) == first
    assert _load_one(store, 2, snapshot) == second


def test_artifact_association_uses_revision_and_expected_stages(store, snapshot, images) -> None:
    _store_one(store, 1, snapshot, images)
    different_stages = (CompositionVisibility(), CompositionVisibility(attribution=True))
    with pytest.raises(ArtifactValidationError, match="exactly 2 stages"):
        _load_one(store, 1, different_stages)


def test_missing_revision_is_distinct_from_incomplete_set(store, snapshot) -> None:
    assert _load_one(store, 1, snapshot[:1]) is None
    directory = store.root / "revision-1"
    directory.mkdir(parents=True)
    with pytest.raises(ArtifactValidationError, match="manifest.json"):
        _load_one(store, 1, snapshot[:1])


@pytest.mark.parametrize("damage", ["missing", "corrupt", "truncated"])
def test_missing_or_damaged_stage_is_rejected(store, snapshot, images, damage) -> None:
    result = _store_one(store, 1, snapshot, images)
    path = _variant(result).stage_paths[1]
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"not an image")
    else:
        path.write_bytes(path.read_bytes()[:45])
    with pytest.raises(ArtifactValidationError):
        _load_one(store, 1, snapshot)
    with pytest.raises(ArtifactValidationError):
        result.load_stage(_SPECIFICATION, 1)


@pytest.mark.parametrize("damage", ["missing", "invalid-json", "checksum", "duplicate", "not-object"])
def test_missing_or_corrupt_manifest_is_rejected(store, snapshot, images, damage) -> None:
    result = _store_one(store, 1, snapshot, images)
    path = result.directory / "manifest.json"
    if damage == "missing":
        path.unlink()
    elif damage == "invalid-json":
        path.write_bytes(b'{"artifacts":')
    elif damage == "checksum":
        document = json.loads(path.read_bytes())
        document["sha256"] = "0" * 64
        path.write_text(json.dumps(document), encoding="utf-8")
    elif damage == "duplicate":
        path.write_bytes(b'{"artifacts": {}, "artifacts": {}}')
    else:
        path.write_bytes(b"null")
    with pytest.raises(ArtifactValidationError):
        _load_one(store, 1, snapshot)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(revision=2),
        lambda m: m.update(revision=True),
        lambda m: m["variants"][0].update(requested_size=[33, 24]),
        lambda m: m["variants"][0].update(requested_size=[32.0, 24]),
        lambda m: m["variants"][0].update(requested_size=[32, 32]),
        lambda m: m["variants"][0].update(aspect_ratio="unknown"),
        lambda m: m["variants"][0].update(mode="P"),
        lambda m: m["variants"][0].update(mode=[]),
        lambda m: m["variants"][0].update(stages=[]),
        lambda m: m["variants"][0]["stages"].reverse(),
        lambda m: m["variants"][0]["stages"][0].update(path="../outside.png"),
        lambda m: m["variants"][0]["stages"][0].update(sha256="invalid"),
        lambda m: m.update(image_directory="../outside"),
        lambda m: m["variants"][0].pop("mode"),
        lambda m: m.update(unknown=True),
    ],
)
def test_inconsistent_manifest_is_rejected_even_with_recomputed_checksum(store, snapshot, images, mutation) -> None:
    result = _store_one(store, 1, snapshot, images)
    rewrite_manifest(result, mutation)
    with pytest.raises(ArtifactValidationError):
        _load_one(store, 1, snapshot)


@pytest.mark.parametrize("replacement", ["dimensions", "mode", "format", "truncated", "crc"])
def test_image_representation_and_decoding_are_checked_beyond_digest(store, snapshot, images, replacement) -> None:
    result = _store_one(store, 1, snapshot, images)
    path = _variant(result).stage_paths[0]
    if replacement == "truncated":
        path.write_bytes(path.read_bytes()[:45])
    elif replacement == "crc":
        data = bytearray(path.read_bytes())
        data[data.index(b"IDAT") + 4] ^= 1
        path.write_bytes(data)
    else:
        mode = "L" if replacement == "mode" else "RGB"
        size = (31, 24) if replacement == "dimensions" else (32, 24)
        with Image.new(mode, size) as image:
            image.save(path, format="BMP" if replacement == "format" else "PNG")
    rewrite_manifest(
        result,
        lambda m: m["variants"][0]["stages"][0].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
    )
    with pytest.raises(ArtifactValidationError):
        _load_one(store, 1, snapshot)


def test_stage_count_and_extra_files_are_rejected(store, snapshot, images) -> None:
    result = _store_one(store, 1, snapshot, images)
    with pytest.raises(ArtifactValidationError, match="exactly 2 stages"):
        _load_one(store, 1, snapshot[:2])
    stage_paths = _variant(result).stage_paths
    (stage_paths[0].parent / "stage-3.png").write_bytes(stage_paths[0].read_bytes())
    with pytest.raises(ArtifactValidationError, match="exactly the expected stage"):
        _load_one(store, 1, snapshot)


@pytest.mark.parametrize("point", ["save", "file-sync", "directory-sync", "payload-rename", "manifest-replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_failed_publication_never_exposes_partial_set(store, snapshot, images, monkeypatch, point, existing) -> None:
    previous = _store_one(store, 1, snapshot, images) if existing else None
    previous_manifest = (previous.directory / "manifest.json").read_bytes() if existing else None
    original_replace = artifacts.os.replace

    def fail(*args, **kwargs):
        raise OSError("injected disk failure")

    def replace_with_failure(source, target):
        if (point == "manifest-replace" and Path(target).name == "manifest.json") or (
            point == "payload-rename" and Path(target).name.startswith("images-")
        ):
            fail()
        original_replace(source, target)

    with monkeypatch.context() as patch:
        if point == "save":
            patch.setattr(Image.Image, "save", fail)
        elif point == "file-sync":
            patch.setattr(artifacts.os, "fsync", fail)
        elif point == "directory-sync":
            patch.setattr(artifacts, "_sync_directory", fail)
        else:
            patch.setattr(artifacts.os, "replace", replace_with_failure)
        with pytest.raises(ArtifactWriteError, match="injected disk failure") as failure:
            _store_one(store, 1, snapshot, tuple(reversed(images)))
        assert not failure.value.published

    if existing:
        assert (previous.directory / "manifest.json").read_bytes() == previous_manifest
        assert PreparedImageArtifactStore(store.root).load(1, snapshot, (_SPECIFICATION,)) == previous
    else:
        try:
            result = PreparedImageArtifactStore(store.root).load(1, snapshot, (_SPECIFICATION,))
        except ArtifactValidationError:
            result = None
        assert result is None


def test_multi_variant_publication_failure_keeps_previous_complete_set(store, snapshot, images, monkeypatch) -> None:
    other_specification = ResolvedOutputSpecification("16:9", (32, 24))
    with Image.new("RGB", (32, 24), "navy") as other_image:
        other_images = tuple(other_image.copy() for _ in snapshot)
    try:
        previous = store.store(1, snapshot, {_SPECIFICATION: images, other_specification: other_images})
        original_replace = artifacts.os.replace

        def fail_manifest(source, target):
            if Path(target).name == "manifest.json":
                raise OSError("manifest publication interrupted")
            original_replace(source, target)

        monkeypatch.setattr(artifacts.os, "replace", fail_manifest)
        with pytest.raises(ArtifactWriteError) as failure:
            store.store(1, snapshot, {_SPECIFICATION: tuple(reversed(images)), other_specification: other_images})
        assert not failure.value.published
    finally:
        for image in other_images:
            image.close()
    assert store.load(1, snapshot, (other_specification, _SPECIFICATION)) == previous


def test_post_publication_sync_failure_reports_complete_new_set(store, snapshot, images, monkeypatch) -> None:
    previous = _store_one(store, 1, snapshot, images)
    original_sync = artifacts._sync_directory

    def fail_after_publication(path):
        if path.name.startswith("images-"):
            raise OSError("directory sync failed")
        original_sync(path)

    monkeypatch.setattr(artifacts, "_sync_directory", fail_after_publication)
    with pytest.raises(ArtifactWriteError, match="complete set published") as failure:
        _store_one(store, 1, snapshot, tuple(reversed(images)))
    assert failure.value.published
    result = _load_one(store, 1, snapshot)
    assert result != previous
    with result.load_stage(_SPECIFICATION, 0) as image:
        assert image.tobytes() == images[-1].tobytes()


def test_replacement_and_validation_release_images(store, snapshot, images, monkeypatch) -> None:
    previous = _store_one(store, 1, snapshot, images)
    result = _store_one(store, 1, snapshot, tuple(reversed(images)))
    references = []
    original = artifacts.PreparedImageArtifactVariant.load_stage

    def capture(self, stage):
        image = original(self, stage)
        references.append(weakref.ref(image))
        return image

    monkeypatch.setattr(artifacts.PreparedImageArtifactVariant, "load_stage", capture)
    assert _load_one(store, 1, snapshot) == result
    gc.collect()
    assert len(references) == 3
    assert all(reference() is None for reference in references)
    with previous.load_stage(_SPECIFICATION, 0) as image:
        assert image.tobytes() == images[0].tobytes()


def test_reveal_advancement_reuses_artifacts_and_artifact_operations_do_not_modify_state(
    store, snapshot, selected_snapshot, images, tmp_path, monkeypatch
) -> None:
    quotation = Quotation(selected_snapshot.quotation_text, selected_snapshot.quotation_identity)
    candidate = QuotationCandidate(quotation, ContentEntry("entry", (quotation,)))
    proposal = SelectionProposal(candidate, frozenset({quotation.identity}), False, 0)
    state_store = PersistentStateStore(tmp_path / "authoritative" / "state.json")
    state = state_store.commit(proposal, selected_snapshot)
    result = _store_one(store, state.revision, snapshot, images)
    advanced = state_store.advance_reveal_progress(state.revision, 2)
    before = state_store.path.read_bytes()
    assert advanced.revision == state.revision
    assert _load_one(store, advanced.revision, snapshot) == result
    store.cleanup(advanced.revision)
    with monkeypatch.context() as patch:
        patch.setattr(artifacts.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(ArtifactWriteError):
            _store_one(store, advanced.revision, snapshot, images)
    assert state_store.path.read_bytes() == before
    assert state_store.load() == advanced


def test_cleanup_removes_old_revisions_and_abandoned_transactions_but_preserves_active(store, snapshot, images) -> None:
    store.cleanup(1)
    first = _store_one(store, 1, snapshot, images)
    current = _store_one(store, 2, snapshot, images)
    temporary = store.root / (".tmp-revision-2-" + "a" * 32)
    temporary.mkdir()
    (temporary / "stage-0.png").write_bytes(b"interrupted")
    store.cleanup(2)
    assert not first.directory.exists()
    assert not temporary.exists()
    assert _load_one(store, 2, snapshot) == current
    (current.directory / "manifest.json").unlink()
    store.cleanup(2)
    assert current.directory.is_dir()
    assert all(path.exists() for path in _variant(current).stage_paths)


def test_cleanup_removes_superseded_active_payloads_and_preserves_manifest_target(store, snapshot, images) -> None:
    superseded = _store_one(store, 2, snapshot, images)
    current = _store_one(store, 2, snapshot, tuple(reversed(images)))
    unrelated = current.directory / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    unowned_payload = current.directory / ("images-" + "f" * 32)
    unowned_payload.mkdir()
    (unowned_payload / "user-file").write_text("keep", encoding="utf-8")

    store.cleanup(2)

    assert not _variant(superseded).stage_paths[0].parent.parent.exists()
    assert _variant(current).stage_paths[0].parent.parent.is_dir()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert (unowned_payload / "user-file").read_text(encoding="utf-8") == "keep"
    assert _load_one(store, 2, snapshot) == current

    store.cleanup(2)
    assert {path.name for path in current.directory.iterdir()} == {
        _variant(current).stage_paths[0].parent.parent.name,
        "manifest.json",
        unrelated.name,
        unowned_payload.name,
    }


def test_cleanup_removes_payload_from_interrupted_active_revision_replacement(
    store, snapshot, images, monkeypatch
) -> None:
    current = _store_one(store, 2, snapshot, images)
    original_replace = artifacts.os.replace

    def interrupt_manifest(source, target):
        if Path(target).name == "manifest.json":
            raise OSError("manifest publication interrupted")
        original_replace(source, target)

    monkeypatch.setattr(artifacts.os, "replace", interrupt_manifest)
    with pytest.raises(ArtifactWriteError, match="manifest publication interrupted"):
        _store_one(store, 2, snapshot, tuple(reversed(images)))

    assert _load_one(store, 2, snapshot) == current
    store.cleanup(2)

    assert {path.name for path in current.directory.iterdir()} == {
        _variant(current).stage_paths[0].parent.parent.name,
        "manifest.json",
    }
    assert _load_one(store, 2, snapshot) == current


@pytest.mark.parametrize("point", ["save", "manifest"])
def test_cleanup_handles_real_interrupted_transactions(store, snapshot, images, monkeypatch, point) -> None:
    original = artifacts.os.replace

    def fail(*args, **kwargs):
        raise OSError("interrupted")

    def interrupt_manifest(source, target):
        if Path(target).name == "manifest.json":
            fail()
        original(source, target)

    with monkeypatch.context() as patch:
        if point == "save":
            patch.setattr(Image.Image, "save", fail)
        else:
            patch.setattr(artifacts.os, "replace", interrupt_manifest)
        with pytest.raises(ArtifactWriteError):
            _store_one(store, 1, snapshot, images)
    current = _store_one(store, 2, snapshot, images)
    store.cleanup(2)
    assert tuple(store.root.iterdir()) == (current.directory,)
    assert _load_one(store, 2, snapshot) == current


def test_cleanup_preserves_unrecognized_files_and_trees(store, snapshot, images) -> None:
    current = _store_one(store, 2, snapshot, images)
    unrelated = [
        store.root / "notes.txt",
        store.root / "revision-01",
        store.root / ".tmp-revision-1-not-ours",
        store.root / "revision-3",
    ]
    for path in unrelated[:3]:
        path.write_text("unrelated", encoding="utf-8")
    unrelated[-1].mkdir()
    (unrelated[-1] / "user-file").write_text("keep", encoding="utf-8")
    store.cleanup(2)
    assert all(path.exists() for path in unrelated)
    assert _load_one(store, 2, snapshot) == current


def test_cleanup_does_not_follow_links_or_remove_link_bearing_trees(
    store, snapshot, images, tmp_path, symlink_or_skip
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "state.json"
    sentinel.write_bytes(b"authoritative")
    old = _store_one(store, 1, snapshot, images)
    current = _store_one(store, 2, snapshot, images)
    symlink_or_skip(store.root / "revision-3", outside, directory=True)
    symlink_or_skip(_variant(old).stage_paths[0].parent / "stage-9.png", sentinel)
    temporary = store.root / (".tmp-revision-9-" + "a" * 32)
    symlink_or_skip(temporary, outside, directory=True)
    active_payload_link = current.directory / ("images-" + "b" * 32)
    symlink_or_skip(active_payload_link, outside, directory=True)
    store.cleanup(2)
    assert sentinel.read_bytes() == b"authoritative"
    assert (store.root / "revision-3").is_symlink()
    assert temporary.is_symlink()
    assert active_payload_link.is_symlink()
    assert old.directory.exists()
    assert _load_one(store, 2, snapshot) == current


@pytest.mark.parametrize("location", ["root", "ancestor", "revision", "payload", "stage", "manifest"])
def test_links_are_not_accepted_for_loading_or_storage(
    store, snapshot, images, tmp_path, location, symlink_or_skip
) -> None:
    result = _store_one(store, 1, snapshot, images)
    if location == "ancestor":
        alias = tmp_path / "alias"
        symlink_or_skip(alias, store.root.parent, directory=True)
        store = PreparedImageArtifactStore(alias / store.root.name)
    else:
        path = {
            "root": store.root,
            "revision": result.directory,
            "payload": _variant(result).stage_paths[0].parent.parent,
            "stage": _variant(result).stage_paths[0],
            "manifest": result.directory / "manifest.json",
        }[location]
        moved = tmp_path / "moved"
        path.rename(moved)
        symlink_or_skip(path, moved, directory=moved.is_dir())
    error = ArtifactAccessError if location in {"root", "ancestor"} else ArtifactValidationError
    with pytest.raises(error, match="link"):
        _load_one(store, 1, snapshot)
    if location in {"root", "ancestor", "revision"}:
        with pytest.raises(ArtifactWriteError, match="link"):
            _store_one(store, 1, snapshot, images)
    if location in {"root", "ancestor"}:
        with pytest.raises(ArtifactCleanupError, match="link"):
            store.cleanup(1)


@pytest.mark.parametrize("operation", ["inspect", "remove", "sync"])
def test_cleanup_failure_is_reported_without_invalidating_current(
    store, snapshot, images, monkeypatch, operation
) -> None:
    old = _store_one(store, 1, snapshot, images)
    current = _store_one(store, 2, snapshot, images)

    def fail(*args):
        raise PermissionError("cleanup denied")

    with monkeypatch.context() as patch:
        if operation == "inspect":
            original = Path.iterdir

            def inspect(path):
                if path == old.directory:
                    fail()
                return original(path)

            patch.setattr(Path, "iterdir", inspect)
        elif operation == "remove":
            patch.setattr(artifacts.shutil, "rmtree", fail)
        else:
            patch.setattr(artifacts, "_sync_directory", fail)
        with pytest.raises(ArtifactCleanupError, match="cleanup denied"):
            store.cleanup(2)
    assert PreparedImageArtifactStore(store.root).load(2, snapshot, (_SPECIFICATION,)) == current


@pytest.mark.parametrize("revision", [0, -1, True, "1"])
def test_invalid_revisions_fail_before_io(store, snapshot, images, revision) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        store.store(revision, snapshot, {_SPECIFICATION: images})
    with pytest.raises(ValueError, match="positive integer"):
        store.load(revision, snapshot, (_SPECIFICATION,))
    with pytest.raises(ValueError, match="positive integer"):
        store.cleanup(revision)
    assert not store.root.exists()


@pytest.mark.parametrize("mode,size", [("P", (32, 24)), ("CMYK", (32, 24))])
def test_invalid_images_fail_before_io(store, snapshot, mode, size) -> None:
    with Image.new(mode, size) as image:
        with pytest.raises(ValueError, match="stage 0"):
            store.store(1, snapshot[:1], {_SPECIFICATION: (image,)})
    assert not store.root.exists()


def test_invalid_api_inputs(store, snapshot, images) -> None:
    with pytest.raises(ValueError, match="absolute"):
        PreparedImageArtifactStore(Path("relative"))
    with pytest.raises(ValueError, match="nonempty"):
        store.store(1, snapshot, {})
    with pytest.raises(ValueError, match="CompositionVisibility"):
        store.store(1, None, {_SPECIFICATION: images})
    with pytest.raises(ValueError, match="nonempty"):
        store.store(1, (), {_SPECIFICATION: images})
    with Image.new("L", (32, 24)) as image:
        with pytest.raises(ValueError, match="same image mode"):
            store.store(1, snapshot[:2], {_SPECIFICATION: (images[0], image)})
    with pytest.raises(ValueError, match="nonempty"):
        store.load(1, (), (_SPECIFICATION,))
    result = _store_one(store, 1, snapshot, images)
    for stage in (-1, 3, True, "0"):
        with pytest.raises(ValueError, match="stage"):
            result.load_stage(_SPECIFICATION, stage)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory synchronization contract")
def test_successful_publication_synchronizes_files_and_directories(store, snapshot, images, monkeypatch) -> None:
    calls = []
    original = artifacts.os.fsync

    def capture(descriptor):
        calls.append(descriptor)
        original(descriptor)

    monkeypatch.setattr(artifacts.os, "fsync", capture)
    _store_one(store, 1, snapshot, images)
    assert len(calls) >= len(images) + 1 + 5


@pytest.mark.parametrize("created", ["ancestor", "root", "revision"])
def test_retry_resynchronizes_parent_of_previously_created_directory(
    store, snapshot, images, monkeypatch, created
) -> None:
    directory = {
        "ancestor": store.root.parent,
        "root": store.root,
        "revision": store.root / "revision-1",
    }[created]
    original = artifacts._sync_directory
    failed = False

    def interrupt_creation(path):
        nonlocal failed
        if path == directory.parent and directory.exists() and not failed:
            failed = True
            raise OSError("new directory entry not synchronized")
        original(path)

    with monkeypatch.context() as patch:
        patch.setattr(artifacts, "_sync_directory", interrupt_creation)
        with pytest.raises(ArtifactWriteError, match="not synchronized"):
            _store_one(store, 1, snapshot, images)
    assert directory.exists()
    calls = []

    def capture(path):
        calls.append(path)
        original(path)

    monkeypatch.setattr(artifacts, "_sync_directory", capture)
    _store_one(store, 1, snapshot, images)
    assert directory.parent in calls
    assert _load_one(store, 1, snapshot) is not None

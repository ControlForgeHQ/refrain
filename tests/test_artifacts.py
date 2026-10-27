from __future__ import annotations

import gc
import hashlib
import json
import os
import weakref
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

import refrain.artifacts as artifacts
from refrain import (
    ArtifactCleanupError,
    ArtifactValidationError,
    ArtifactWriteError,
    ContentEntry,
    DailySnapshot,
    PersistentStateStore,
    PreparedImageArtifactSet,
    PreparedImageArtifactStore,
    Quotation,
    QuotationCandidate,
    ResolvedFont,
    SchedulingContext,
    SelectionProposal,
)


@pytest.fixture
def snapshot() -> DailySnapshot:
    return DailySnapshot(
        quotation_text="A thought worth keeping.",
        quotation_identity="A thought worth keeping.",
        font=ResolvedFont("test", b"self-contained font bytes"),
        presentation_metadata={"source": "Collection", "attribution": "Author", "presentation_style": "centered"},
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        layout={"image_size": (32, 24), "nested": {"values": [1, True, None]}},
        scheduling=SchedulingContext(date(2026, 10, 26), "Etc/UTC", "06:00"),
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
    result = store.store(1, snapshot, images[:count])
    assert result.directory == store.root / "revision-1"
    assert tuple(path.name for path in result.stage_paths) == tuple(f"stage-{i}.png" for i in range(count))
    for path, original in zip(result.stage_paths, images):
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == original.size
            assert image.mode == original.mode
            assert image.tobytes() == original.tobytes()
    reloaded = PreparedImageArtifactStore(store.root).load(1, snapshot, stage_count=count)
    assert reloaded == result
    with reloaded.load_stage(count - 1) as image:
        assert image.tobytes() == images[count - 1].tobytes()


@pytest.mark.parametrize("mode", ["1", "L", "LA", "RGB", "RGBA"])
def test_supported_modes_are_preserved_losslessly(store, snapshot, mode) -> None:
    with Image.new(mode, (32, 24)) as image:
        result = store.store(1, snapshot, (image,))
        with result.load_stage(0) as loaded:
            assert loaded.mode == mode
            assert loaded.tobytes() == image.tobytes()


def test_revisions_have_distinct_locations(store, snapshot, images) -> None:
    first = store.store(1, snapshot, images)
    second = store.store(2, snapshot, images)
    assert first.directory != second.directory
    assert store.load(1, snapshot, stage_count=3) == first
    assert store.load(2, snapshot, stage_count=3) == second


@pytest.mark.parametrize(
    "changes",
    [
        {"quotation_text": "Another thought.", "quotation_identity": "Another thought."},
        {"font": ResolvedFont("test", b"different font bytes")},
        {"font": ResolvedFont("another-identifier", b"self-contained font bytes")},
        {"presentation_metadata": {"source": "Changed"}},
        {"reveal_schedule": {"quotation": "07:00"}},
        {"layout": {"image_size": (32, 24), "other": 1}},
        {"scheduling": SchedulingContext(date(2026, 10, 27), "Etc/UTC", "06:00")},
        {"scheduling": SchedulingContext(date(2026, 10, 26), "Europe/London", "07:00")},
    ],
)
def test_same_revision_does_not_override_snapshot_association(store, snapshot, images, changes) -> None:
    store.store(1, snapshot, images)
    with pytest.raises(ArtifactValidationError, match="expected committed snapshot"):
        store.load(1, replace(snapshot, **changes), stage_count=3)


def test_missing_revision_is_distinct_from_incomplete_set(store, snapshot) -> None:
    assert store.load(1, snapshot, stage_count=1) is None
    directory = store.root / "revision-1"
    directory.mkdir(parents=True)
    with pytest.raises(ArtifactValidationError, match="manifest.json"):
        store.load(1, snapshot, stage_count=1)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "truncated"])
def test_missing_or_damaged_stage_is_rejected(store, snapshot, images, damage) -> None:
    result = store.store(1, snapshot, images)
    path = result.stage_paths[1]
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"not an image")
    else:
        path.write_bytes(path.read_bytes()[:45])
    with pytest.raises(ArtifactValidationError):
        store.load(1, snapshot, stage_count=3)
    with pytest.raises(ArtifactValidationError):
        result.load_stage(1)


@pytest.mark.parametrize("damage", ["missing", "invalid-json", "checksum", "duplicate", "not-object"])
def test_missing_or_corrupt_manifest_is_rejected(store, snapshot, images, damage) -> None:
    result = store.store(1, snapshot, images)
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
        store.load(1, snapshot, stage_count=3)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(format_version=2),
        lambda m: m.update(format_version=True),
        lambda m: m.update(revision=2),
        lambda m: m.update(revision=True),
        lambda m: m.update(image_size=[33, 24]),
        lambda m: m.update(image_size=[32.0, 24]),
        lambda m: m.update(mode="P"),
        lambda m: m.update(mode=[]),
        lambda m: m.update(stages=[]),
        lambda m: m["stages"].reverse(),
        lambda m: m["stages"][0].update(file="../outside.png"),
        lambda m: m["stages"][0].update(sha256="invalid"),
        lambda m: m.update(image_directory="../outside"),
        lambda m: m.pop("mode"),
        lambda m: m.update(unknown=True),
    ],
)
def test_inconsistent_manifest_is_rejected_even_with_recomputed_checksum(store, snapshot, images, mutation) -> None:
    result = store.store(1, snapshot, images)
    rewrite_manifest(result, mutation)
    with pytest.raises(ArtifactValidationError):
        store.load(1, snapshot, stage_count=3)


@pytest.mark.parametrize("replacement", ["dimensions", "mode", "format", "truncated", "crc"])
def test_image_representation_and_decoding_are_checked_beyond_digest(store, snapshot, images, replacement) -> None:
    result = store.store(1, snapshot, images)
    path = result.stage_paths[0]
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
    rewrite_manifest(result, lambda m: m["stages"][0].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    with pytest.raises(ArtifactValidationError):
        store.load(1, snapshot, stage_count=3)


def test_stage_count_and_extra_files_are_rejected(store, snapshot, images) -> None:
    result = store.store(1, snapshot, images)
    with pytest.raises(ArtifactValidationError, match="exactly 2 stages"):
        store.load(1, snapshot, stage_count=2)
    (result.stage_paths[0].parent / "stage-3.png").write_bytes(result.stage_paths[0].read_bytes())
    with pytest.raises(ArtifactValidationError, match="exactly the expected stage"):
        store.load(1, snapshot, stage_count=3)


@pytest.mark.parametrize("point", ["save", "file-sync", "directory-sync", "payload-rename", "manifest-replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_failed_publication_never_exposes_partial_set(store, snapshot, images, monkeypatch, point, existing) -> None:
    previous = store.store(1, snapshot, images) if existing else None
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
            store.store(1, snapshot, tuple(reversed(images)))
        assert not failure.value.published

    if existing:
        assert (previous.directory / "manifest.json").read_bytes() == previous_manifest
        assert PreparedImageArtifactStore(store.root).load(1, snapshot, stage_count=3) == previous
    else:
        try:
            result = PreparedImageArtifactStore(store.root).load(1, snapshot, stage_count=3)
        except ArtifactValidationError:
            result = None
        assert result is None


def test_post_publication_sync_failure_reports_complete_new_set(store, snapshot, images, monkeypatch) -> None:
    previous = store.store(1, snapshot, images)
    original_sync = artifacts._sync_directory

    def fail_after_publication(path):
        if path.name.startswith("images-"):
            raise OSError("directory sync failed")
        original_sync(path)

    monkeypatch.setattr(artifacts, "_sync_directory", fail_after_publication)
    with pytest.raises(ArtifactWriteError, match="complete set published") as failure:
        store.store(1, snapshot, tuple(reversed(images)))
    assert failure.value.published
    result = store.load(1, snapshot, stage_count=3)
    assert result != previous
    with result.load_stage(0) as image:
        assert image.tobytes() == images[-1].tobytes()


def test_replacement_and_validation_release_images(store, snapshot, images, monkeypatch) -> None:
    previous = store.store(1, snapshot, images)
    result = store.store(1, snapshot, tuple(reversed(images)))
    references = []
    original = PreparedImageArtifactSet.load_stage

    def capture(self, stage):
        image = original(self, stage)
        references.append(weakref.ref(image))
        return image

    monkeypatch.setattr(PreparedImageArtifactSet, "load_stage", capture)
    assert store.load(1, snapshot, stage_count=3) == result
    gc.collect()
    assert len(references) == 3
    assert all(reference() is None for reference in references)
    with previous.load_stage(0) as image:
        assert image.tobytes() == images[0].tobytes()


def test_reveal_advancement_reuses_artifacts_and_artifact_operations_do_not_modify_state(
    store, snapshot, images, tmp_path, monkeypatch
) -> None:
    quotation = Quotation(snapshot.quotation_text, snapshot.quotation_identity)
    candidate = QuotationCandidate(quotation, ContentEntry("entry", (quotation,)))
    proposal = SelectionProposal(candidate, frozenset({quotation.identity}), False, 0)
    state_store = PersistentStateStore(tmp_path / "authoritative" / "state.json")
    state = state_store.commit(proposal, snapshot)
    result = store.store(state.revision, state.snapshot, images)
    advanced = state_store.advance_reveal_progress(state.revision, 2)
    before = state_store.path.read_bytes()
    assert advanced.revision == state.revision
    assert store.load(advanced.revision, advanced.snapshot, stage_count=3) == result
    store.cleanup(advanced.revision)
    with monkeypatch.context() as patch:
        patch.setattr(artifacts.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(ArtifactWriteError):
            store.store(advanced.revision, advanced.snapshot, images)
    assert state_store.path.read_bytes() == before
    assert state_store.load() == advanced


def test_cleanup_removes_old_revisions_and_abandoned_transactions_but_preserves_active(store, snapshot, images) -> None:
    store.cleanup(1)
    first = store.store(1, snapshot, images)
    current = store.store(2, snapshot, images)
    temporary = store.root / (".tmp-revision-2-" + "a" * 32)
    temporary.mkdir()
    (temporary / "stage-0.png").write_bytes(b"interrupted")
    store.cleanup(2)
    assert not first.directory.exists()
    assert not temporary.exists()
    assert store.load(2, snapshot, stage_count=3) == current
    (current.directory / "manifest.json").unlink()
    store.cleanup(2)
    assert current.directory.is_dir()
    assert all(path.exists() for path in current.stage_paths)


def test_cleanup_preserves_unrecognized_files_and_trees(store, snapshot, images) -> None:
    current = store.store(2, snapshot, images)
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
    assert store.load(2, snapshot, stage_count=3) == current


def symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")


def test_cleanup_does_not_follow_links_or_remove_link_bearing_trees(store, snapshot, images, tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "state.json"
    sentinel.write_bytes(b"authoritative")
    old = store.store(1, snapshot, images)
    current = store.store(2, snapshot, images)
    symlink_or_skip(store.root / "revision-3", outside, directory=True)
    symlink_or_skip(old.stage_paths[0].parent / "stage-9.png", sentinel)
    temporary = store.root / (".tmp-revision-9-" + "a" * 32)
    symlink_or_skip(temporary, outside, directory=True)
    store.cleanup(2)
    assert sentinel.read_bytes() == b"authoritative"
    assert (store.root / "revision-3").is_symlink()
    assert temporary.is_symlink()
    assert old.directory.exists()
    assert store.load(2, snapshot, stage_count=3) == current


@pytest.mark.parametrize("location", ["root", "ancestor", "revision", "payload", "stage", "manifest"])
def test_links_are_not_accepted_for_loading_or_storage(store, snapshot, images, tmp_path, location) -> None:
    result = store.store(1, snapshot, images)
    if location == "ancestor":
        alias = tmp_path / "alias"
        symlink_or_skip(alias, store.root.parent, directory=True)
        store = PreparedImageArtifactStore(alias / store.root.name)
    else:
        path = {
            "root": store.root,
            "revision": result.directory,
            "payload": result.stage_paths[0].parent,
            "stage": result.stage_paths[0],
            "manifest": result.directory / "manifest.json",
        }[location]
        moved = tmp_path / "moved"
        path.rename(moved)
        symlink_or_skip(path, moved, directory=moved.is_dir())
    with pytest.raises(ArtifactValidationError, match="link"):
        store.load(1, snapshot, stage_count=3)
    if location in {"root", "ancestor", "revision"}:
        with pytest.raises(ArtifactWriteError, match="link"):
            store.store(1, snapshot, images)
    if location in {"root", "ancestor"}:
        with pytest.raises(ArtifactCleanupError, match="link"):
            store.cleanup(1)


@pytest.mark.parametrize("operation", ["inspect", "remove", "sync"])
def test_cleanup_failure_is_reported_without_invalidating_current(
    store, snapshot, images, monkeypatch, operation
) -> None:
    old = store.store(1, snapshot, images)
    current = store.store(2, snapshot, images)

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
    assert PreparedImageArtifactStore(store.root).load(2, snapshot, stage_count=3) == current


@pytest.mark.parametrize("revision", [0, -1, True, "1"])
def test_invalid_revisions_fail_before_io(store, snapshot, images, revision) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        store.store(revision, snapshot, images)
    with pytest.raises(ValueError, match="positive integer"):
        store.load(revision, snapshot, stage_count=3)
    with pytest.raises(ValueError, match="positive integer"):
        store.cleanup(revision)
    assert not store.root.exists()


@pytest.mark.parametrize("mode,size", [("P", (32, 24)), ("CMYK", (32, 24)), ("RGB", (1, 1))])
def test_invalid_images_fail_before_io(store, snapshot, mode, size) -> None:
    with Image.new(mode, size) as image:
        with pytest.raises(ValueError, match="stage 0"):
            store.store(1, snapshot, (image,))
    assert not store.root.exists()


def test_invalid_api_inputs(store, snapshot, images) -> None:
    with pytest.raises(ValueError, match="absolute"):
        PreparedImageArtifactStore(Path("relative"))
    with pytest.raises(ValueError, match="nonempty"):
        store.store(1, snapshot, ())
    with pytest.raises(TypeError, match="DailySnapshot"):
        store.store(1, None, images)
    with pytest.raises(ValueError, match="image_size"):
        store.store(1, replace(snapshot, layout={}), images)
    with Image.new("L", (32, 24)) as image:
        with pytest.raises(ValueError, match="same image mode"):
            store.store(1, snapshot, (images[0], image))
    for count in (0, True, -1):
        with pytest.raises(ValueError, match="stage_count"):
            store.load(1, snapshot, stage_count=count)
    result = store.store(1, snapshot, images)
    for stage in (-1, 3, True, "0"):
        with pytest.raises(ValueError, match="stage"):
            result.load_stage(stage)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory synchronization contract")
def test_successful_publication_synchronizes_files_and_directories(store, snapshot, images, monkeypatch) -> None:
    calls = []
    original = artifacts.os.fsync

    def capture(descriptor):
        calls.append(descriptor)
        original(descriptor)

    monkeypatch.setattr(artifacts.os, "fsync", capture)
    store.store(1, snapshot, images)
    assert len(calls) >= len(images) + 1 + 4

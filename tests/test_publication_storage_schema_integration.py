from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone

import pytest
from PIL import Image

from refrain.config import DisplayOutputConfiguration
from refrain.display import DisplayBackendUpdateError
from refrain.display.publication import FilesystemPublicationDisplayBackend
from refrain.geometry import ResolvedOutputSpecification
from refrain.publication_metadata import finalize_publication_metadata
from refrain.publication_storage import PublicationManifest, PublicationStorageError, PublicationStore

OUTPUT = ResolvedOutputSpecification("16:9", (16, 9))
PRESENTATION = {
    "style": "centered",
    "background": "none",
    "decoration": "none",
    "fonts": {
        "bundle": "example",
        "faces": {"quotation": "regular", "source": "regular", "attribution": "regular"},
    },
    "colors": {"text": "black", "decoration": None},
    "font_size_range": {"minimum": 12, "maximum": 32},
    "insets": {"left": 0, "right": 0, "top": 0, "bottom": 0},
}
CHECKPOINT = {
    "schema_version": 1,
    "content": {
        "display_date": "2026-11-18",
        "selection_revision": 1,
        "reveal_schedule": {"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        "reveal_stage": {"quotation": True, "source": False, "attribution": False},
        "quotation": "A quotation.",
        "actions": [
            {"type": "public", "visibility": ["external"], "payload": "public"},
            {"type": "private", "visibility": ["internal"], "payload": "private"},
        ],
        "qr": [{"payload": "private", "visibility": ["internal"]}],
    },
    "presentation": PRESENTATION,
}


def transient(identifier: str, destination: str = "screen") -> dict[str, object]:
    return finalize_publication_metadata(
        publication_type="transient",
        publication_id=identifier,
        published_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
        destination_id=destination,
        output_specification=OUTPUT,
    )


def test_transient_store_uses_exact_manifest_and_nested_metadata(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        manifest = store.publish("screen", image, transient("event"))
    raw = json.loads((tmp_path / "publish" / "screen" / "manifest.json").read_bytes())
    assert set(raw) == {
        "schema_version",
        "id",
        "image_filename",
        "metadata_filename",
        "image_sha256",
        "metadata_sha256",
    }
    assert raw["id"] == "event"
    assert store.read_current("screen").manifest == manifest
    assert store.read_current("screen").metadata == transient("event")


@pytest.mark.parametrize("identifier", ["manifest", "MANIFEST", "CON", "con"])
def test_reserved_manifest_id_is_rejected_before_publication(tmp_path, identifier) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(PublicationStorageError):
            store.publish("screen", image, transient(identifier))
    assert not store.root.exists()


def test_backend_finalizes_checkpoint_and_image_association(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    backend = FilesystemPublicationDisplayBackend(store)
    destination = DisplayOutputConfiguration("screen", OUTPUT, audience="internal")
    association = {
        "checkpoint": copy.deepcopy(CHECKPOINT),
        "selection_revision": 1,
        "visibility": {"quotation": True, "source": False, "attribution": False},
        "effective_presentation": copy.deepcopy(PRESENTATION),
        "rendered_qr": {"payload": "private", "visibility": ["internal"]},
        "output_specification": {"aspect_ratio": "16:9", "requested_output_size": [16, 9]},
    }
    original = copy.deepcopy(association)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        backend.publish_scheduled(destination, image, association)
    dataset = store.read_current("screen")
    assert dataset.metadata["publication"]["type"] == "scheduled"
    assert [action["type"] for action in dataset.metadata["content"]["actions"]] == ["private"]
    assert dataset.metadata["content"]["qr"] == [association["rendered_qr"]]
    assert association == original


def test_backend_reassociates_shared_qr_with_each_destination_audience(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    backend = FilesystemPublicationDisplayBackend(store)
    checkpoint = copy.deepcopy(CHECKPOINT)
    checkpoint["content"]["qr"] = [
        {"payload": "shared", "visibility": ["external"]},
        {"payload": "shared", "visibility": ["internal"]},
    ]
    association = {
        "checkpoint": checkpoint,
        "selection_revision": 1,
        "visibility": {"quotation": True, "source": False, "attribution": False},
        "effective_presentation": copy.deepcopy(PRESENTATION),
        "rendered_qr": {"payload": "shared", "visibility": ["external"]},
        "output_specification": {"aspect_ratio": "16:9", "requested_output_size": [16, 9]},
    }
    original = copy.deepcopy(association)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        for audience in ("external", "internal"):
            backend.publish_scheduled(
                DisplayOutputConfiguration(audience, OUTPUT, audience=audience), image, association
            )
    assert store.read_current("external").metadata["content"]["qr"] == [
        {"payload": "shared", "visibility": ["external"]}
    ]
    assert store.read_current("internal").metadata["content"]["qr"] == [
        {"payload": "shared", "visibility": ["internal"]}
    ]
    assert association == original


def test_backend_rejects_qr_missing_for_destination_audience(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    backend = FilesystemPublicationDisplayBackend(store)
    association = {
        "checkpoint": copy.deepcopy(CHECKPOINT),
        "selection_revision": 1,
        "visibility": {"quotation": True, "source": False, "attribution": False},
        "effective_presentation": copy.deepcopy(PRESENTATION),
        "rendered_qr": {"payload": "private", "visibility": ["internal"]},
        "output_specification": {"aspect_ratio": "16:9", "requested_output_size": [16, 9]},
    }
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(DisplayBackendUpdateError, match="destination audience"):
            backend.publish_scheduled(
                DisplayOutputConfiguration("external", OUTPUT, audience="external"), image, association
            )
    assert not store.root.exists()


def test_manifest_replacement_is_verified_before_acknowledgement(tmp_path, monkeypatch) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    replace = store._replace_manifest

    def replace_and_damage(source, target):
        replace(source, target)
        (target.parent / "new.png").write_bytes(b"damaged")

    monkeypatch.setattr(store, "_replace_manifest", replace_and_damage)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(PublicationStorageError) as error:
            store.publish("screen", image, transient("new"))
    assert error.value.published
    assert (store.root / "screen" / "old.png").is_file()
    with pytest.raises(PublicationStorageError, match="hash"):
        store.read_current("screen")


def test_manifest_parser_rejects_legacy_field_and_reserved_id() -> None:
    manifest = PublicationManifest("event", "event.png", "event.json", "a" * 64, "b" * 64)
    from refrain.publication_storage import parse_publication_manifest

    legacy = manifest.to_mapping()
    legacy["publication_id"] = legacy.pop("id")
    with pytest.raises(PublicationStorageError):
        parse_publication_manifest(json.dumps(legacy))
    bad = manifest.to_mapping()
    bad.update(id="manifest", image_filename="manifest.png", metadata_filename="manifest.json")
    with pytest.raises(PublicationStorageError):
        parse_publication_manifest(json.dumps(bad))


@pytest.mark.parametrize("damage", ["legacy", "bad-hash", "missing-image", "missing-manifest", "oversized", "utf8"])
def test_owned_directory_replaces_damaged_dataset(tmp_path, damage) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    destination = store.root / "screen"
    manifest_path = destination / "manifest.json"
    if damage == "missing-manifest":
        manifest_path.unlink()
    elif damage == "missing-image":
        (destination / "old.png").unlink()
    elif damage == "oversized":
        manifest_path.write_bytes(b"x" * (64 * 1024 + 1))
    elif damage == "utf8":
        manifest_path.write_bytes(b"\xff")
    else:
        manifest = json.loads(manifest_path.read_bytes())
        if damage == "legacy":
            manifest["publication_id"] = manifest.pop("id")
        else:
            manifest["image_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("new"))
    assert store.read_current("screen").manifest.publication_id == "new"
    assert (destination / ".refrain-owned").read_bytes() == b""


def test_unmarked_invalid_dataset_is_not_adopted_or_changed(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    destination = store.root / "screen"
    destination.mkdir(parents=True)
    legacy = b'{"schema_version":1,"publication_id":"old"}'
    (destination / "manifest.json").write_bytes(legacy)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(PublicationStorageError, match="cannot adopt"):
            store.publish("screen", image, transient("new"))
    assert (destination / "manifest.json").read_bytes() == legacy
    assert not (destination / ".refrain-owned").exists()


def test_unmarked_unknown_directory_is_not_adopted_or_cleaned(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    destination = store.root / "screen"
    unknown = destination / "unknown"
    unknown.mkdir(parents=True)
    sentinel = unknown / "data.bin"
    sentinel.write_bytes(b"preserve")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(PublicationStorageError, match="cannot adopt"):
            store.publish("screen", image, transient("new"))
    assert sentinel.read_bytes() == b"preserve"
    assert not (destination / ".refrain-owned").exists()
    assert not (destination / "manifest.json").exists()


@pytest.mark.parametrize(
    "invalid_manifest",
    [b'{"schema_version":1,"publication_id":"old"}', b"x" * (64 * 1024 + 1), b"\xff"],
    ids=["legacy", "oversized", "invalid-utf8"],
)
def test_owned_invalid_dataset_survives_precommit_failure(tmp_path, monkeypatch, invalid_manifest) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    destination = store.root / "screen"
    manifest_path = destination / "manifest.json"
    manifest_path.write_bytes(invalid_manifest)
    monkeypatch.setattr(store, "_replace_manifest", lambda *_args: (_ for _ in ()).throw(OSError("interrupted")))
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(PublicationStorageError, match="before manifest commit"):
            store.publish("screen", image, transient("new"))
    assert manifest_path.read_bytes() == invalid_manifest
    assert (destination / "old.png").is_file()
    assert (destination / "old.json").is_file()
    assert (destination / ".refrain-owned").is_file()


def test_oversized_manifest_ambiguous_replacement_is_verified(tmp_path, monkeypatch, caplog) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    (store.root / "screen" / "manifest.json").write_bytes(b"x" * (64 * 1024 + 1))
    replace = store._replace_manifest

    def replace_then_raise(source, target):
        replace(source, target)
        raise OSError("replacement outcome interrupted")

    monkeypatch.setattr(store, "_replace_manifest", replace_then_raise)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        manifest = store.publish("screen", image, transient("new"))
    assert store.read_current("screen").manifest == manifest
    assert manifest.publication_id == "new"
    assert "committed despite a replacement error" in caplog.text


def test_complete_unmarked_dataset_can_be_adopted(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    marker = store.root / "screen" / ".refrain-owned"
    marker.unlink()
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("new"))
    assert marker.read_bytes() == b""
    assert store.read_current("screen").manifest.publication_id == "new"


def test_nonempty_marker_is_rejected_without_dataset_changes(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    marker = store.root / "screen" / ".refrain-owned"
    marker.write_bytes(b"invalid")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        with pytest.raises(PublicationStorageError, match="ownership marker"):
            store.publish("screen", image, transient("new"))
    assert store.read_current("screen").manifest.publication_id == "old"


def test_owned_cleanup_removes_unknown_files_and_nested_directories(tmp_path) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    destination = store.root / "screen"
    (destination / "notes.txt").write_text("obsolete", encoding="utf-8")
    nested = destination / "unknown" / "nested"
    nested.mkdir(parents=True)
    (nested / "data.bin").write_bytes(b"obsolete")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("new"))
    assert {path.name for path in destination.iterdir()} == {
        ".refrain-owned",
        "manifest.json",
        "new.json",
        "new.png",
    }


def test_owned_cleanup_unlinks_contained_links_without_following_targets(tmp_path, symlink_or_skip) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    destination = store.root / "screen"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    symlink_or_skip(destination / "file-link", sentinel)
    nested = destination / "obsolete"
    nested.mkdir()
    symlink_or_skip(nested / "directory-link", outside, directory=True)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("new"))
    assert sentinel.read_bytes() == b"preserve"
    assert not (destination / "file-link").exists()
    assert not nested.exists()


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "O_NOFOLLOW"), reason="POSIX descriptor-based cleanup")
def test_cleanup_rejects_directory_replaced_by_symlink(tmp_path, monkeypatch, symlink_or_skip, caplog) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    destination = store.root / "screen"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    candidate = destination / "obsolete"
    candidate.mkdir()
    probe = tmp_path / "probe"
    symlink_or_skip(probe, outside, directory=True)
    probe.unlink()
    open_file = os.open
    changed = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal changed
        if path == "obsolete" and kwargs.get("dir_fd") is not None and not changed:
            changed = True
            candidate.rename(destination / "moved")
            candidate.symlink_to(outside, target_is_directory=True)
        return open_file(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        manifest = store.publish("screen", image, transient("new"))
    assert changed
    assert "cleanup failed" in caplog.text
    assert sentinel.read_bytes() == b"preserve"
    assert store.read_current("screen").manifest == manifest


def test_windows_cleanup_fails_closed_before_traversal_or_deletion(tmp_path, monkeypatch) -> None:
    store = PublicationStore(tmp_path / "publish")
    destination = store.root / "screen"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    destination.mkdir(parents=True)
    (destination / ".refrain-owned").touch()
    unknown = destination / "unknown"
    unknown.mkdir()
    (unknown / "data").write_bytes(b"preserve")

    def deny_enumeration(_path):
        raise AssertionError("Windows cleanup must not enumerate any path")

    monkeypatch.setattr(type(destination), "iterdir", deny_enumeration)
    with pytest.raises(PublicationStorageError, match="non-following cleanup is unavailable"):
        store._cleanup_windows_directory(destination, {".refrain-owned"})
    assert (unknown / "data").read_bytes() == b"preserve"
    assert sentinel.read_bytes() == b"preserve"


def test_windows_cleanup_failure_preserves_verified_commit(tmp_path, monkeypatch, caplog) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    monkeypatch.setattr(store, "_cleanup_contents", store._cleanup_windows_directory)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        manifest = store.publish("screen", image, transient("new"))
    assert "cleanup failed" in caplog.text
    assert "non-following cleanup is unavailable" in caplog.text
    assert manifest.publication_id == "new"
    assert store.read_current("screen").manifest == manifest
    assert (store.root / "screen" / "old.png").is_file()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are unavailable")
def test_cleanup_rejects_special_files_without_invalidating_committed_dataset(tmp_path, caplog) -> None:
    store = PublicationStore(tmp_path / "publish")
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        store.publish("screen", image, transient("old"))
    fifo = store.root / "screen" / "pipe"
    os.mkfifo(fifo)
    with Image.new("RGB", OUTPUT.requested_output_size) as image:
        manifest = store.publish("screen", image, transient("new"))
    assert "cleanup failed" in caplog.text
    assert fifo.exists()
    assert store.read_current("screen").manifest == manifest

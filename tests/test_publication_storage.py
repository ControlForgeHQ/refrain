from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import refrain.publication_storage as publication_storage_module
from refrain.geometry import ResolvedOutputSpecification
from refrain.paths import ApplicationPaths
from refrain.publication_metadata import finalize_publication_metadata
from refrain.publication_storage import (
    PUBLICATION_MANIFEST_VERSION,
    PublicationManifest,
    PublicationStorageError,
    PublicationStore,
    parse_publication_manifest,
    serialize_publication_manifest,
    validate_publication_root,
)

_OUTPUT = ResolvedOutputSpecification("16:9", (16, 9))


def _paths(root: Path) -> ApplicationPaths:
    config = root / "config" / "refrain"
    state = root / "state" / "refrain"
    cache = root / "cache" / "refrain"
    return ApplicationPaths(
        config_directory=config,
        config_file=config / "config.yaml",
        content_directory=config / "content",
        operational_directory=state,
        state_directory=state,
        state_file=state / "state.json",
        history_file=state / "global-history.jsonl",
        cache_directory=cache,
        artifacts_directory=cache / "artifacts",
        publish_directory=state / "publish",
    )


def _metadata(publication_id: str, destination_id: str = "screen") -> dict[str, object]:
    visibility = {"quotation": True, "source": False, "attribution": False}
    presentation = {
        "style": "centered",
        "background": "none",
        "decoration": "none",
        "fonts": {
            "bundle": "lora",
            "faces": {"quotation": "regular", "source": "regular", "attribution": "regular"},
        },
        "colors": {"text": "black", "decoration": None},
        "font_size_range": {"minimum": 12, "maximum": 32},
        "insets": {"left": 0, "right": 0, "top": 0, "bottom": 0},
    }
    checkpoint = {
        "schema_version": 1,
        "content": {
            "display_date": "2026-11-16",
            "selection_revision": 1,
            "reveal_schedule": {"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
            "reveal_stage": visibility,
            "quotation": "A publication-ready quotation.",
            "actions": [],
            "qr": [],
        },
        "presentation": presentation,
    }
    return finalize_publication_metadata(
        checkpoint,
        publication_type="scheduled",
        publication_id=publication_id,
        published_at=datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc),
        destination_id=destination_id,
        output_specification=_OUTPUT,
        audience="internal",
        selection_revision=1,
        visibility=visibility,
        effective_presentation=presentation,
        prepared_output_specification=_OUTPUT,
    )


def _store(root: Path, *, protected_paths=()) -> PublicationStore:
    return PublicationStore(
        root,
        application_paths=_paths(root.parent / "installation"),
        protected_paths=protected_paths,
    )


def _image(value: int = 0) -> Image.Image:
    return Image.new("RGB", _OUTPUT.requested_output_size, (value, 0, 0))


def test_manifest_contract_round_trips_and_rejects_unsafe_or_unknown_values() -> None:
    manifest = PublicationManifest(
        "publication-1",
        "publication-1.png",
        "publication-1.json",
        "a" * 64,
        "b" * 64,
    )
    encoded = serialize_publication_manifest(manifest)

    assert parse_publication_manifest(encoded) == manifest
    assert json.loads(encoded)["schema_version"] == PUBLICATION_MANIFEST_VERSION
    for field, value in (
        ("id", "../outside"),
        ("id", "x" * 241),
        ("image_filename", "../outside.png"),
        ("metadata_filename", "/outside.json"),
        ("image_sha256", "A" * 64),
        ("extra", True),
    ):
        document = manifest.to_mapping()
        document[field] = value
        with pytest.raises(PublicationStorageError):
            parse_publication_manifest(json.dumps(document))
    unsupported = manifest.to_mapping()
    unsupported["schema_version"] = 2
    with pytest.raises(PublicationStorageError, match="unsupported"):
        parse_publication_manifest(json.dumps(unsupported))
    with pytest.raises(PublicationStorageError, match="duplicate"):
        parse_publication_manifest(encoded.decode().replace("{", '{"schema_version":1,', 1))


@pytest.mark.parametrize("destination_id", ["", ".", "..", "../escape", "a/b", "x" * 257])
def test_invalid_destination_identifiers_are_rejected_before_path_creation(tmp_path: Path, destination_id: str) -> None:
    store = _store(tmp_path / "publish")
    with pytest.raises(PublicationStorageError, match="destination_id"):
        store.publish(destination_id, _image(), _metadata("pub-1"), audience="internal")
    assert not (tmp_path / "publish").exists()


def test_initial_publish_replacement_hash_verification_and_destination_isolation(tmp_path: Path) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as first_image:
        first_manifest = store.publish("screen", first_image, _metadata("publication-1"), audience="internal")
    first_dataset = store.read_current("screen")
    assert first_dataset.manifest == first_manifest
    assert first_dataset.metadata["publication"]["id"] == "publication-1"
    assert hashlib.sha256(first_dataset.image).hexdigest() == first_manifest.image_sha256
    assert (store.root / "screen" / "publication-1.png").is_file()

    with _image(2) as second_image:
        second_manifest = store.publish("screen", second_image, _metadata("publication-2"), audience="internal")
    current = store.read_current("screen")
    assert current.manifest == second_manifest
    assert current.metadata["publication"]["id"] == "publication-2"
    assert sorted(path.name for path in (store.root / "screen").iterdir()) == [
        ".refrain-owned",
        "manifest.json",
        "publication-2.json",
        "publication-2.png",
    ]

    with _image(3) as other_image:
        store.publish("other", other_image, _metadata("publication-3", "other"), audience="internal")
    assert store.read_current("screen").manifest.publication_id == "publication-2"
    assert store.read_current("other").manifest.publication_id == "publication-3"


def test_publication_rejects_metadata_association_and_image_dimension_mismatches(tmp_path: Path) -> None:
    store = _store(tmp_path / "publish")
    with pytest.raises(PublicationStorageError, match="destination"):
        store.publish("screen", _image(), _metadata("pub-1", "other"), audience="internal")
    with pytest.raises(PublicationStorageError, match="dimensions"):
        store.publish(
            "screen",
            Image.new("RGB", (9, 16)),
            _metadata("pub-1"),
            audience="internal",
        )
    assert not store.root.exists()


def test_transient_completed_metadata_can_be_stored_without_scheduled_context(tmp_path: Path) -> None:
    store = _store(tmp_path / "publish")
    metadata = finalize_publication_metadata(
        publication_type="transient",
        publication_id="transient-1",
        published_at=datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc),
        destination_id="screen",
        output_specification=_OUTPUT,
    )
    with _image(4) as image:
        store.publish("screen", image, metadata)

    dataset = store.read_current("screen")
    assert dataset.metadata["publication"]["type"] == "transient"
    assert set(dataset.metadata) == {"schema_version", "publication"}


@pytest.mark.parametrize("failure_point", ["image", "metadata", "manifest", "replace"])
def test_precommit_failures_preserve_the_previous_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    previous_manifest = (store.root / "screen" / "manifest.json").read_bytes()

    if failure_point == "image":

        def fail_image(path: Path, _image_value: Image.Image) -> None:
            path.write_bytes(b"partial image")
            raise OSError("image write interrupted")

        monkeypatch.setattr(store, "_write_image", fail_image)
    elif failure_point == "metadata":
        original = store._write_bytes

        def fail_metadata(path: Path, contents: bytes) -> None:
            if path.name == "new.json":
                path.write_bytes(b"partial metadata")
                raise OSError("metadata write interrupted")
            original(path, contents)

        monkeypatch.setattr(store, "_write_bytes", fail_metadata)
    elif failure_point == "manifest":
        original = store._write_bytes

        def fail_manifest(path: Path, contents: bytes) -> None:
            if path.name.endswith(".manifest.tmp"):
                path.write_bytes(b"partial manifest")
                raise OSError("manifest write interrupted")
            original(path, contents)

        monkeypatch.setattr(store, "_write_bytes", fail_manifest)
    else:
        monkeypatch.setattr(store, "_replace_manifest", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))

    with _image(2) as image, pytest.raises(PublicationStorageError, match="before manifest commit") as error:
        store.publish("screen", image, _metadata("new"), audience="internal")
    assert error.value.published is False
    assert (store.root / "screen" / "manifest.json").read_bytes() == previous_manifest
    assert store.read_current("screen").manifest.publication_id == "old"
    assert not (store.root / "screen" / "new.png").exists()
    assert not (store.root / "screen" / "new.json").exists()


def test_replacement_failure_after_os_replace_reports_committed_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    replace = store._replace_manifest

    def replace_then_fail(temporary: Path, manifest: Path) -> None:
        replace(temporary, manifest)
        raise OSError("post-replacement interruption")

    monkeypatch.setattr(store, "_replace_manifest", replace_then_fail)
    with _image(2) as image:
        manifest = store.publish("screen", image, _metadata("new"), audience="internal")
    assert store.read_current("screen").manifest == manifest
    assert manifest.publication_id == "new"
    assert "committed despite a replacement error" in caplog.text
    assert "post-replacement interruption" in caplog.text


def test_postcommit_cleanup_failure_keeps_the_new_dataset_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    monkeypatch.setattr(
        store,
        "_cleanup_contents",
        lambda *_args: (_ for _ in ()).throw(PublicationStorageError("cleanup interrupted")),
    )
    with _image(2) as image:
        manifest = store.publish("screen", image, _metadata("new"), audience="internal")
    assert store.read_current("screen").manifest == manifest
    assert manifest.publication_id == "new"
    assert "cleanup failed" in caplog.text
    assert "cleanup interrupted" in caplog.text
    assert (store.root / "screen" / "old.png").is_file()


def test_stale_and_unknown_contents_in_owned_directory_are_reconciled(tmp_path: Path) -> None:
    root = tmp_path / "publish"
    destination = root / "screen"
    destination.mkdir(parents=True)
    (destination / ".refrain-owned").touch()
    (destination / "orphan.png").write_bytes(b"interrupted image")
    stale = destination / (".refrain-" + "0" * 32 + ".manifest.tmp")
    stale.write_bytes(b"interrupted manifest")
    store = _store(root)
    with _image() as image:
        store.publish("screen", image, _metadata("current"), audience="internal")
    assert not (destination / "orphan.png").exists()
    assert not stale.exists()

    unknown = destination / "user-file.txt"
    unknown.write_text("obsolete")
    with _image(1) as image:
        store.publish("screen", image, _metadata("next"), audience="internal")
    assert not unknown.exists()
    assert store.read_current("screen").manifest.publication_id == "next"


@pytest.mark.parametrize("corruption", ["malformed", "missing-image", "bad-hash"])
def test_owned_invalid_publication_can_be_replaced(tmp_path: Path, corruption: str) -> None:
    store = _store(tmp_path / "publish")
    with _image() as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    manifest_path = store.root / "screen" / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = parse_publication_manifest(original_manifest)
    if corruption == "malformed":
        manifest_path.write_text('{"schema_version":2}')
    elif corruption == "missing-image":
        (store.root / "screen" / manifest.image_filename).unlink()
    else:
        document = manifest.to_mapping()
        document["image_sha256"] = "0" * 64
        manifest_path.write_bytes(json.dumps(document).encode())
    damaged_manifest = manifest_path.read_bytes()
    if corruption == "malformed":
        assert original_manifest != damaged_manifest
    with pytest.raises(PublicationStorageError):
        store.read_current("screen")
    with _image(1) as image:
        manifest = store.publish("screen", image, _metadata("next"), audience="internal")
    assert store.read_current("screen").manifest == manifest
    assert manifest.publication_id == "next"
    assert (store.root / "screen" / ".refrain-owned").read_bytes() == b""


def test_manifest_swap_exposes_only_complete_old_or_new_datasets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    observations = []
    replace = store._replace_manifest

    def inspect_commit(temporary: Path, manifest: Path) -> None:
        observations.append(store.read_current("screen").manifest.publication_id)
        replace(temporary, manifest)
        dataset = store.read_current("screen")
        observations.append(dataset.manifest.publication_id)
        assert hashlib.sha256(dataset.image).hexdigest() == dataset.manifest.image_sha256

    monkeypatch.setattr(store, "_replace_manifest", inspect_commit)
    with _image(2) as image:
        store.publish("screen", image, _metadata("new"), audience="internal")
    assert observations == ["old", "new"]


def test_reader_retries_when_cleanup_races_with_manifest_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    read_dataset = store._read_dataset
    replaced = False

    def replace_before_read(destination: Path, manifest: PublicationManifest):
        nonlocal replaced
        if manifest.publication_id == "old" and not replaced:
            replaced = True
            with _image(2) as image:
                _store(store.root).publish("screen", image, _metadata("new"), audience="internal")
        return read_dataset(destination, manifest)

    monkeypatch.setattr(store, "_read_dataset", replace_before_read)

    dataset = store.read_current("screen")

    assert dataset.manifest.publication_id == "new"
    assert hashlib.sha256(dataset.image).hexdigest() == dataset.manifest.image_sha256


def test_reader_retries_when_initial_manifest_appears_after_first_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "publish"
    destination = root / "screen"
    destination.mkdir(parents=True)
    store = _store(root)
    load_current = store._load_current
    appeared = False

    def publish_after_missing_manifest(path: Path):
        nonlocal appeared
        dataset = load_current(path)
        if dataset is None and not appeared:
            appeared = True
            with _image() as image:
                _store(root).publish("screen", image, _metadata("initial"), audience="internal")
        return dataset

    monkeypatch.setattr(store, "_load_current", publish_after_missing_manifest)

    dataset = store.read_current("screen")

    assert dataset.manifest.publication_id == "initial"


@pytest.mark.parametrize("mode", ["1", "L", "LA", "P", "RGB", "RGBA", "I;16"])
def test_writer_images_in_supported_png_modes_remain_readable(tmp_path: Path, mode: str) -> None:
    store = _store(tmp_path / "publish")
    with Image.new(mode, _OUTPUT.requested_output_size) as image:
        manifest = store.publish("screen", image, _metadata("pub"), audience="internal")
    dataset = store.read_current("screen")
    assert dataset.manifest == manifest
    with Image.open(BytesIO(dataset.image)) as image:
        assert image.size == _OUTPUT.requested_output_size
        image.load()


def test_image_reads_are_bounded_for_writer_and_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path / "publish")
    read_file = publication_storage_module._read_regular_file
    limits = []

    def observe_read(path: Path, *, limit: int | None = None) -> bytes:
        if path.suffix == ".png":
            limits.append(limit)
        return read_file(path, limit=limit)

    monkeypatch.setattr(publication_storage_module, "_read_regular_file", observe_read)
    with _image() as image:
        store.publish("screen", image, _metadata("pub"), audience="internal")
    store.read_current("screen")
    assert len(limits) >= 3
    assert all(limit == publication_storage_module._MAX_IMAGE_BYTES for limit in limits)


def test_regular_file_read_enforces_limit_during_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "image.png"
    original_fdopen = publication_storage_module.os.fdopen
    reads = []

    class ObservedRead:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, size=-1):
            reads.append(size)
            return self.source.read(size)

    monkeypatch.setattr(
        publication_storage_module.os,
        "fdopen",
        lambda fd, *args, **kwargs: ObservedRead(original_fdopen(fd, *args, **kwargs)),
    )
    path.write_bytes(b"x" * 128)
    assert publication_storage_module._read_regular_file(path, limit=128) == b"x" * 128
    path.write_bytes(b"x" * 129)
    with pytest.raises(PublicationStorageError, match="size limit"):
        publication_storage_module._read_regular_file(path, limit=128)
    assert publication_storage_module._read_regular_file(path, limit=64 * 1024 * 1024) == b"x" * 129
    assert reads == [129, 1, 129, 1024 * 1024, 1024 * 1024]


@pytest.mark.parametrize("operation", ["fstat", "fdopen"])
def test_regular_file_descriptor_errors_are_verification_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(b"image")

    def fail(*_args, **_kwargs):
        raise OSError("injected descriptor failure")

    monkeypatch.setattr(publication_storage_module.os, operation, fail)
    with pytest.raises(PublicationStorageError, match="cannot read publication file"):
        publication_storage_module._read_regular_file(path, limit=128)


def test_oversized_image_is_rejected_by_reader_and_before_writer_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "publish")
    with _image() as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    destination = store.root / "screen"
    original_manifest = (destination / "manifest.json").read_bytes()
    monkeypatch.setattr(publication_storage_module, "_MAX_IMAGE_BYTES", 32)
    with pytest.raises(PublicationStorageError, match="size limit"):
        store.read_current("screen")
    with _image(1) as image, pytest.raises(PublicationStorageError, match="size limit"):
        store.publish("screen", image, _metadata("new"), audience="internal")
    assert (destination / "manifest.json").read_bytes() == original_manifest
    assert not (destination / "new.png").exists()
    monkeypatch.undo()
    assert store.read_current("screen").manifest.publication_id == "old"


@pytest.mark.parametrize("damage", ["jpeg", "dimensions", "truncated", "iend-crc", "trailing", "animated"])
def test_reader_rejects_invalid_image_even_with_matching_hash(tmp_path: Path, damage: str) -> None:
    store = _store(tmp_path / "publish")
    with _image() as image:
        store.publish("screen", image, _metadata("pub"), audience="internal")
    destination = store.root / "screen"
    image_path = destination / "pub.png"
    if damage == "truncated":
        image_bytes = image_path.read_bytes()[:-4]
    elif damage == "iend-crc":
        image_bytes = image_path.read_bytes()[:-1] + b"\x00"
    elif damage == "trailing":
        image_bytes = image_path.read_bytes() + b"extra"
    else:
        buffer = BytesIO()
        size = (9, 16) if damage == "dimensions" else _OUTPUT.requested_output_size
        with Image.new("RGB", size) as image:
            if damage == "animated":
                with Image.new("RGB", size, "red") as second:
                    image.save(buffer, format="PNG", save_all=True, append_images=[second])
            else:
                image.save(buffer, format="JPEG" if damage == "jpeg" else "PNG")
        image_bytes = buffer.getvalue()
    image_path.write_bytes(image_bytes)
    manifest_path = destination / "manifest.json"
    manifest = parse_publication_manifest(manifest_path.read_bytes())
    manifest_path.write_bytes(
        serialize_publication_manifest(replace(manifest, image_sha256=hashlib.sha256(image_bytes).hexdigest()))
    )
    with pytest.raises(PublicationStorageError):
        store.read_current("screen")


def test_image_dimensions_are_checked_before_full_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = BytesIO()
    with Image.new("RGB", (20, 20)) as image:
        image.save(buffer, format="PNG")

    def fail_load(*_args, **_kwargs):
        pytest.fail("mismatched image must not be decoded")

    monkeypatch.setattr(Image.Image, "load", fail_load)
    with pytest.raises(PublicationStorageError, match="dimensions"):
        publication_storage_module._matches_image(buffer.getvalue(), _OUTPUT.requested_output_size)


@pytest.mark.parametrize("filename", ["manifest.json", "old.png", "old.json"])
@pytest.mark.parametrize("persistent", [False, True])
def test_read_errors_retry_from_current_manifest_and_exhaust_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, persistent: bool
) -> None:
    store = _store(tmp_path / "publish")
    with _image() as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    original_open = publication_storage_module.os.open
    original_fdopen = publication_storage_module.os.fdopen
    opened = {}
    failures = 0

    def track_open(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        opened[fd] = Path(path).name
        return fd

    class FailingRead:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, size=-1):
            nonlocal failures
            failures += 1
            if not persistent:
                with _image(1) as image:
                    _store(store.root).publish("screen", image, _metadata("new"), audience="internal")
            raise OSError("injected read failure")

    def failing_fdopen(fd, *args, **kwargs):
        source = original_fdopen(fd, *args, **kwargs)
        if opened.get(fd) == filename and (persistent or not failures):
            return FailingRead(source)
        return source

    monkeypatch.setattr(publication_storage_module.os, "open", track_open)
    monkeypatch.setattr(publication_storage_module.os, "fdopen", failing_fdopen)
    if persistent:
        with pytest.raises(PublicationStorageError, match="cannot read publication file"):
            store.read_current("screen")
        assert failures == 2
    else:
        assert store.read_current("screen").manifest.publication_id == "new"
        assert failures == 1


def test_missing_destination_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path / "publish")
    destination = store._destination
    attempts = 0

    def publish_after_missing(destination_id: str, *, create: bool) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            with _image() as image:
                _store(store.root).publish("screen", image, _metadata("pub"), audience="internal")
            raise PublicationStorageError("temporarily unavailable")
        return destination(destination_id, create=create)

    monkeypatch.setattr(store, "_destination", publish_after_missing)
    assert store.read_current("screen").manifest.publication_id == "pub"
    assert attempts == 2


def test_unverifiable_manifest_replacement_retains_old_and_new_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "publish")
    with _image(1) as image:
        store.publish("screen", image, _metadata("old"), audience="internal")
    read_current = store.read_current
    monkeypatch.setattr(
        store, "read_current", lambda *_args: (_ for _ in ()).throw(PublicationStorageError("verification unavailable"))
    )
    replace = store._replace_manifest

    def replace_then_fail(temporary: Path, manifest: Path) -> None:
        replace(temporary, manifest)
        raise OSError("replacement outcome interrupted")

    monkeypatch.setattr(store, "_replace_manifest", replace_then_fail)
    with _image(2) as image, pytest.raises(PublicationStorageError, match="outcome is uncertain") as error:
        store.publish("screen", image, _metadata("new"), audience="internal")

    assert error.value.published is True
    assert (store.root / "screen" / "old.png").is_file()
    assert (store.root / "screen" / "new.png").is_file()
    monkeypatch.setattr(store, "read_current", read_current)
    assert store.read_current("screen").manifest.publication_id == "new"


def test_publication_root_rejects_protected_overlap_before_creation(tmp_path: Path) -> None:
    protected = tmp_path / "protected"
    for root in (protected, protected / "nested", protected.parent):
        with pytest.raises(PublicationStorageError, match="overlaps protected"):
            validate_publication_root(
                root,
                protected_paths=(protected,),
                application_paths=_paths(tmp_path / "standard"),
            )
    assert not protected.exists()


@pytest.mark.parametrize(
    "name",
    [
        "state.json",
        "publication.json",
        "global-history.jsonl",
        "global-history.1.jsonl",
        "global-history.19.jsonl",
        "global-history.20.jsonl",
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_custom_state_files_and_future_history_segments_are_protected(tmp_path: Path, name: str, nested: bool) -> None:
    paths = _paths(tmp_path / "installation")
    state = tmp_path / "custom-state"
    configuration = SimpleNamespace(
        file=tmp_path / "configuration" / "config.yaml",
        content_directory=tmp_path / "configuration" / "content",
        storage=SimpleNamespace(state=state, artifacts=None, publish=None),
    )
    root = state / name
    if nested:
        root /= "nested"

    with pytest.raises(PublicationStorageError, match="overlaps protected"):
        validate_publication_root(root, application_paths=paths, configuration=configuration)

    assert not state.exists()


@pytest.mark.parametrize("name", ["publish", "global-history.backup.jsonl", "global-history.1.jsonl-backup"])
def test_custom_state_allows_separate_publication_directories(tmp_path: Path, name: str) -> None:
    paths = _paths(tmp_path / "installation")
    state = tmp_path / "custom-state"
    configuration = SimpleNamespace(
        file=tmp_path / "configuration" / "config.yaml",
        content_directory=tmp_path / "configuration" / "content",
        storage=SimpleNamespace(state=state, artifacts=None, publish=None),
    )
    root = state / name
    assert validate_publication_root(root, application_paths=paths, configuration=configuration) == root


def test_standard_state_future_history_segment_is_protected(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "installation")
    root = paths.state_directory / "global-history.1.jsonl"
    paths = replace(paths, publish_directory=root)
    with pytest.raises(PublicationStorageError, match="overlaps protected"):
        validate_publication_root(root, application_paths=paths)


def test_custom_root_cannot_be_inside_a_standard_purge_tree(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "installation")
    custom_root = Path(paths.operational_directory) / "family-publications"
    store = PublicationStore(custom_root, application_paths=paths)

    with _image() as image, pytest.raises(PublicationStorageError, match="purge-owned directory"):
        store.publish("screen", image, _metadata("publication-1"), audience="internal")

    assert not custom_root.exists()


@pytest.mark.parametrize("use_standard_root", [True, False], ids=["standard", "external-custom"])
def test_standard_and_external_custom_roots_are_accepted(tmp_path: Path, use_standard_root: bool) -> None:
    paths = _paths(tmp_path / "installation")
    root = Path(paths.publish_directory) if use_standard_root else tmp_path / "family-publications"
    store = PublicationStore(root, application_paths=paths)

    with _image() as image:
        store.publish("screen", image, _metadata("publication-1"), audience="internal")

    assert store.read_current("screen").manifest.publication_id == "publication-1"


def test_custom_root_cannot_be_nested_under_standard_publication_storage(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "installation")
    custom_root = Path(paths.publish_directory) / "custom"
    store = PublicationStore(custom_root, application_paths=paths)

    with _image() as image, pytest.raises(PublicationStorageError, match="purge-owned directory"):
        store.publish("screen", image, _metadata("publication-1"), audience="internal")

    assert not paths.publish_directory.exists()


def test_cleanup_rejects_invalid_marker_before_deleting_any(tmp_path: Path) -> None:
    root = tmp_path / "publish"
    destination = root / "screen"
    destination.mkdir(parents=True)
    obsolete = destination / "obsolete.png"
    obsolete.write_bytes(b"keep")
    marker = destination / ".refrain-owned"
    marker.write_bytes(b"invalid")
    store = _store(root)
    with pytest.raises(PublicationStorageError, match="ownership marker"):
        store._cleanup_contents(destination, {"manifest.json"})
    assert obsolete.read_bytes() == b"keep"
    assert marker.read_bytes() == b"invalid"


def test_cleanup_rejects_a_destination_outside_its_publication_root(tmp_path: Path) -> None:
    store = _store(tmp_path / "publish")
    outside = tmp_path / "outside" / "screen"
    outside.mkdir(parents=True)
    sentinel = outside / "obsolete.png"
    sentinel.write_bytes(b"outside")

    with pytest.raises(PublicationStorageError, match="direct child"):
        store._cleanup_contents(outside, set())

    assert sentinel.read_bytes() == b"outside"


def test_create_directory_does_not_attempt_mkdir_on_existing_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing_parent = tmp_path / "existing"
    existing_parent.mkdir()
    target = existing_parent / "created"
    original_mkdir = Path.mkdir

    def deny_mkdir_on_existing(path: Path, *args, **kwargs) -> None:
        if path.exists():
            raise PermissionError(f"attempted mkdir on existing path: {path}")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", deny_mkdir_on_existing)

    publication_storage_module._create_directory(target)

    assert target.is_dir()


def test_publication_root_cannot_overlap_another_configured_publish_path(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "installation")
    configured_root = tmp_path / "configured-publish"
    configuration = SimpleNamespace(
        file=tmp_path / "configuration" / "config.yaml",
        content_directory=tmp_path / "configuration" / "content",
        storage=SimpleNamespace(state=None, history=None, artifacts=None, publish=configured_root),
    )
    store = PublicationStore(
        configured_root / "nested",
        configuration=configuration,
        application_paths=paths,
    )

    with pytest.raises(PublicationStorageError, match="overlaps protected"):
        store._validate_root()


def test_publication_root_and_destination_symlinks_are_rejected(tmp_path: Path, symlink_or_skip) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep"
    sentinel.write_text("outside")

    linked_root = tmp_path / "linked-root"
    symlink_or_skip(linked_root, outside, directory=True)
    with pytest.raises(PublicationStorageError, match="link"):
        _store(linked_root).publish("screen", _image(), _metadata("pub"), audience="internal")
    assert sentinel.read_text() == "outside"

    root = tmp_path / "publish"
    root.mkdir()
    symlink_or_skip(root / "screen", outside, directory=True)
    with pytest.raises(PublicationStorageError, match="link"):
        _store(root).publish("screen", _image(), _metadata("pub"), audience="internal")
    assert sentinel.read_text() == "outside"


def test_manifest_file_symlink_is_rejected_without_following_target(tmp_path: Path, symlink_or_skip) -> None:
    store = _store(tmp_path / "publish")
    destination = store.root / "screen"
    destination.mkdir(parents=True)
    target = tmp_path / "outside-manifest"
    target.write_text("{}")
    symlink_or_skip(destination / "manifest.json", target)
    with pytest.raises(PublicationStorageError, match="regular file|link"):
        store.read_current("screen")
    assert target.read_text() == "{}"


def test_referenced_file_symlink_is_rejected_without_following_target(tmp_path: Path, symlink_or_skip) -> None:
    store = _store(tmp_path / "publish")
    with _image() as image:
        store.publish("screen", image, _metadata("pub"), audience="internal")
    dataset_path = store.root / "screen" / "pub.png"
    outside = tmp_path / "outside.png"
    outside.write_bytes(dataset_path.read_bytes())
    dataset_path.unlink()
    symlink_or_skip(dataset_path, outside)

    with pytest.raises(PublicationStorageError, match="link"):
        store.read_current("screen")
    assert outside.is_file()


def test_destination_directory_has_exactly_the_validated_identifier(tmp_path: Path) -> None:
    store = _store(tmp_path / "publish")
    with _image() as image:
        store.publish("screen_1-2", image, _metadata("pub-1", "screen_1-2"), audience="internal")
    assert (store.root / "screen_1-2" / "manifest.json").is_file()

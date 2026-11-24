"""Hardware-independent storage for one current publication per destination."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image

from .config import _WINDOWS_RESERVED_DESTINATION_IDS, ApplicationConfiguration
from .paths import ApplicationPaths, resolve_application_paths, resolve_publication_root
from .publication_metadata import (
    parse_publication_metadata,
    serialize_publication_metadata,
    validate_publication_metadata,
)

PUBLICATION_MANIFEST_VERSION = 1
_MANIFEST_FIELDS = {
    "schema_version",
    "id",
    "image_filename",
    "metadata_filename",
    "image_sha256",
    "metadata_sha256",
}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}\Z")
_PUBLICATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,239}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TEMPORARY = re.compile(r"\.refrain-[0-9a-f]{32}\.manifest\.tmp\Z")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_METADATA_BYTES = 16 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


def _generated_publication_name(name: str) -> bool:
    stem, suffix = os.path.splitext(name)
    return suffix in {".png", ".json"} and bool(_PUBLICATION_ID.fullmatch(stem))


def _valid_destination_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.fullmatch(value)) and not (
        os.name == "nt" and value.upper() in _WINDOWS_RESERVED_DESTINATION_IDS
    )


class PublicationStorageError(Exception):
    """Raised when a publication cannot be safely committed or recovered."""

    def __init__(self, message: str, *, published: bool = False) -> None:
        super().__init__(message)
        self.published = published


@dataclass(frozen=True)
class PublicationManifest:
    """The versioned index for one complete publication dataset."""

    publication_id: str
    image_filename: str
    metadata_filename: str
    image_sha256: str
    metadata_sha256: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": PUBLICATION_MANIFEST_VERSION,
            "id": self.publication_id,
            "image_filename": self.image_filename,
            "metadata_filename": self.metadata_filename,
            "image_sha256": self.image_sha256,
            "metadata_sha256": self.metadata_sha256,
        }


@dataclass(frozen=True)
class PublicationDataset:
    """A hash-verified dataset read through its current manifest."""

    manifest: PublicationManifest
    image: bytes
    metadata: dict[str, object]


def _validate_manifest(value: object) -> PublicationManifest:
    if not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS:
        raise PublicationStorageError("manifest must contain exactly the supported fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != PUBLICATION_MANIFEST_VERSION:
        raise PublicationStorageError("unsupported publication manifest schema version")
    publication_id = value["id"]
    if (
        not isinstance(publication_id, str)
        or not _PUBLICATION_ID.fullmatch(publication_id)
        or publication_id.casefold() == "manifest"
        or publication_id.upper() in _WINDOWS_RESERVED_DESTINATION_IDS
    ):
        raise PublicationStorageError("manifest id must be a valid identifier of at most 240 characters")
    if value["image_filename"] != f"{publication_id}.png":
        raise PublicationStorageError("manifest image_filename must be the publication's PNG filename")
    if value["metadata_filename"] != f"{publication_id}.json":
        raise PublicationStorageError("manifest metadata_filename must be the publication's JSON filename")
    if not isinstance(value["image_sha256"], str) or not _HASH.fullmatch(value["image_sha256"]):
        raise PublicationStorageError("manifest image_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(value["metadata_sha256"], str) or not _HASH.fullmatch(value["metadata_sha256"]):
        raise PublicationStorageError("manifest metadata_sha256 must be a lowercase SHA-256 digest")
    return PublicationManifest(
        publication_id,
        value["image_filename"],
        value["metadata_filename"],
        value["image_sha256"],
        value["metadata_sha256"],
    )


def parse_publication_manifest(contents: str | bytes) -> PublicationManifest:
    """Parse and strictly validate one versioned publication manifest."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationStorageError(f"manifest contains duplicate field {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise PublicationStorageError(f"manifest contains invalid JSON number {value}")

    if isinstance(contents, bytes):
        try:
            contents = contents.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PublicationStorageError("manifest must be UTF-8 JSON") from error
    if not isinstance(contents, str):
        raise PublicationStorageError("manifest must be UTF-8 JSON text")
    try:
        encoded_length = len(contents.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise PublicationStorageError("manifest must contain valid Unicode text") from error
    if encoded_length > _MAX_MANIFEST_BYTES:
        raise PublicationStorageError("manifest exceeds the supported size limit")
    try:
        value = json.loads(contents, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise PublicationStorageError(f"manifest is not valid JSON: {error}") from error
    return _validate_manifest(value)


def serialize_publication_manifest(manifest: PublicationManifest) -> bytes:
    """Serialize a manifest deterministically as UTF-8 JSON."""
    validated = _validate_manifest(manifest.to_mapping())
    return (
        json.dumps(validated.to_mapping(), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _is_redirect(path: Path, status: os.stat_result) -> bool:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return True
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(status, "st_file_attributes", 0) & reparse_point)


def _check_path_components(path: Path) -> None:
    for candidate in reversed((path, *path.parents)):
        try:
            status = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise PublicationStorageError(f"cannot inspect publication path {candidate}: {error}") from error
        if _is_redirect(candidate, status):
            raise PublicationStorageError(f"refusing to follow a filesystem link or reparse point at {candidate}")
        if candidate != path and not stat.S_ISDIR(status.st_mode):
            raise PublicationStorageError(f"publication path parent is not a directory: {candidate}")


def _absolute(path: str | os.PathLike[str]) -> Path:
    value = Path(path)
    if not value.is_absolute():
        raise PublicationStorageError(f"publication and protected paths must be absolute: {value}")
    return Path(os.path.normpath(os.fspath(value)))


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _standard_purge_roots(paths: ApplicationPaths) -> tuple[Path, ...]:
    candidates = tuple(
        dict.fromkeys(
            Path(path) for path in (paths.config_directory, paths.operational_directory, paths.cache_directory)
        )
    )
    return tuple(
        candidate
        for candidate in candidates
        if not any(candidate != other and candidate.is_relative_to(other) for other in candidates)
    )


def publication_protected_paths(
    paths: ApplicationPaths,
    configuration: ApplicationConfiguration | None = None,
) -> tuple[Path, ...]:
    """Return standard and effective data locations that publication must not overlap."""
    protected: set[Path] = {
        Path(paths.config_file),
        Path(paths.content_directory),
        Path(paths.assets_directory),
        *(Path(path) for path in paths.asset_directories),
        Path(paths.state_file),
        Path(paths.history_file),
        Path(paths.state_directory) / "publication.json",
        Path(paths.cache_directory),
        Path(paths.artifacts_directory),
        Path(paths.ownership_file),
        Path(paths.control_metadata_file),
    }
    if Path(paths.config_directory) != Path(paths.operational_directory):
        protected.add(Path(paths.config_directory))
    if Path(paths.state_directory) != Path(paths.operational_directory):
        protected.add(Path(paths.state_directory))
    if configuration is not None:
        config_directory = Path(configuration.file.parent)
        if config_directory not in {Path(paths.config_directory), Path(paths.operational_directory)}:
            protected.add(config_directory)
        protected.update(
            path
            for path in (
                configuration.content_directory,
                configuration.storage.artifacts,
            )
            if path is not None
        )
        if configuration.storage.state is not None:
            protected.update(
                configuration.storage.state / name
                for name in ("state.json", "global-history.jsonl", "publication.json")
            )
        protected.add(config_directory / "assets")
        protected.update(config_directory / "assets" / category for category in ("fonts", "backgrounds", "decorations"))
    return tuple(sorted(protected, key=os.fspath))


def validate_publication_root(
    root: str | os.PathLike[str],
    *,
    protected_paths: Iterable[str | os.PathLike[str]] = (),
    application_paths: ApplicationPaths | None = None,
    configuration: ApplicationConfiguration | None = None,
) -> Path:
    """Fail closed if a publication root overlaps protected data or traverses a redirect."""
    root_path = _absolute(root)
    paths = application_paths or resolve_application_paths()
    standard_publication_root = _absolute(paths.publish_directory)
    if root_path != standard_publication_root and any(
        root_path.is_relative_to(purge_root) for purge_root in _standard_purge_roots(paths)
    ):
        raise PublicationStorageError(
            f"custom publication root {root_path} is inside a standard purge-owned directory; "
            "choose a directory outside the standard Refrain installation"
        )
    protected = set(publication_protected_paths(paths, configuration))
    protected.update(Path(path) for path in protected_paths)
    _check_path_components(root_path)
    history_paths = [Path(paths.history_file)]
    if configuration is not None and configuration.storage.state is not None:
        history_paths.append(configuration.storage.state / "global-history.jsonl")
    for history_path in history_paths:
        history_path = _absolute(history_path)
        if root_path.is_relative_to(history_path.parent) and root_path != history_path.parent:
            component = root_path.relative_to(history_path.parent).parts[0]
            pattern = rf"{re.escape(history_path.stem)}\.\d+{re.escape(history_path.suffix)}"
            if re.fullmatch(pattern, component, re.IGNORECASE if os.name == "nt" else 0):
                raise PublicationStorageError(
                    f"publication root {root_path} overlaps protected Refrain storage "
                    f"{history_path.parent / component}; choose a separate directory"
                )
    for path in protected:
        normalized = _absolute(path)
        _check_path_components(normalized)
        if _overlaps(root_path, normalized):
            raise PublicationStorageError(
                f"publication root {root_path} overlaps protected Refrain storage {normalized}; "
                "choose a separate directory"
            )
    _check_path_components(root_path)
    try:
        status = root_path.lstat()
    except FileNotFoundError:
        return root_path
    except OSError as error:
        raise PublicationStorageError(f"cannot inspect publication root {root_path}: {error}") from error
    if not stat.S_ISDIR(status.st_mode):
        raise PublicationStorageError(f"publication root is not a directory: {root_path}")
    return root_path


def validate_publication_tree(root: str | os.PathLike[str], *, application_paths: ApplicationPaths) -> Path:
    """Validate a standard publication tree before installation maintenance removes it."""
    root_path = validate_publication_root(root, application_paths=application_paths)
    try:
        root_path.lstat()
    except FileNotFoundError:
        return root_path
    except OSError as error:
        raise PublicationStorageError(f"cannot inspect publication root {root_path}: {error}") from error

    def inspect(directory: Path, *, is_root: bool = False) -> None:
        try:
            children = tuple(directory.iterdir())
        except OSError as error:
            raise PublicationStorageError(f"cannot inspect publication directory {directory}: {error}") from error
        for child in children:
            try:
                status = child.lstat()
            except OSError as error:
                raise PublicationStorageError(f"cannot inspect publication object {child}: {error}") from error
            if _is_redirect(child, status):
                raise PublicationStorageError(f"refusing to remove a linked publication object: {child}")
            if is_root:
                if not _valid_destination_identifier(child.name) or not stat.S_ISDIR(status.st_mode):
                    raise PublicationStorageError(f"refusing to remove an unexpected publication object: {child}")
                inspect(child)
            elif not stat.S_ISREG(status.st_mode) or not (
                child.name == "manifest.json"
                or _generated_publication_name(child.name)
                or _TEMPORARY.fullmatch(child.name)
            ):
                raise PublicationStorageError(f"refusing to remove an unexpected publication object: {child}")

    inspect(root_path, is_root=True)
    return root_path


def _create_directory(path: Path) -> None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        if path.parent != path:
            _create_directory(path.parent)
        try:
            path.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise PublicationStorageError(f"cannot create publication directory {path}: {error}") from error
    except OSError as error:
        raise PublicationStorageError(f"cannot inspect publication directory {path}: {error}") from error
    else:
        if _is_redirect(path, status):
            raise PublicationStorageError(f"refusing to follow a filesystem link or reparse point at {path}")
        if not stat.S_ISDIR(status.st_mode):
            raise PublicationStorageError(f"publication path is not a directory: {path}")
    _check_path_components(path)
    try:
        status = path.lstat()
    except OSError as error:
        raise PublicationStorageError(f"cannot inspect publication directory {path}: {error}") from error
    if not stat.S_ISDIR(status.st_mode):
        raise PublicationStorageError(f"publication path is not a directory: {path}")


def _read_regular_file(path: Path, *, limit: int | None = None) -> bytes:
    _check_path_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise PublicationStorageError(f"cannot read publication file {path}: {error}") from error
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PublicationStorageError(f"publication file is not a regular file: {path}")
        with os.fdopen(fd, "rb") as source:
            fd = -1
            contents = source.read() if limit is None else source.read(limit + 1)
        if limit is not None and len(contents) > limit:
            raise PublicationStorageError(f"publication file exceeds the supported size limit: {path}")
        return contents
    finally:
        if fd >= 0:
            os.close(fd)


def _manifest_snapshot(path: Path) -> tuple[int, str] | None:
    """Identify a possibly damaged manifest without allocating its full contents."""
    _check_path_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise PublicationStorageError(f"cannot read publication manifest {path}: {error}") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PublicationStorageError(f"publication manifest is not a regular file: {path}")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb") as source:
            fd = -1
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
            after = os.fstat(source.fileno())
        if (
            not os.path.samestat(before, after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise PublicationStorageError(f"publication manifest changed while being read: {path}")
        return after.st_size, digest.hexdigest()
    except OSError as error:
        raise PublicationStorageError(f"cannot read publication manifest {path}: {error}") from error
    finally:
        if fd >= 0:
            os.close(fd)


def _open_exclusive(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o666)
    except OSError as error:
        raise PublicationStorageError(f"cannot create publication file {path}: {error}") from error
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise PublicationStorageError(f"publication output is not a regular file: {path}")
    return os.fdopen(fd, "wb")


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as error:
        raise PublicationStorageError(f"cannot synchronize publication directory {path}: {error}") from error


def _matches_image(image: bytes, expected_size: tuple[int, int]) -> None:
    try:
        with Image.open(BytesIO(image)) as decoded:
            if decoded.format != "PNG" or getattr(decoded, "n_frames", 1) != 1:
                raise PublicationStorageError("published image must be a single-frame PNG")
            if decoded.size != expected_size:
                raise PublicationStorageError("published image dimensions do not match completed metadata")
            decoded.load()
    except PublicationStorageError:
        raise
    except Exception as error:
        raise PublicationStorageError(f"published image is not a valid PNG: {error}") from error


class PublicationStore:
    """Commit and recover one current, hash-verified publication per destination."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        configuration: ApplicationConfiguration | None = None,
        application_paths: ApplicationPaths | None = None,
        protected_paths: Iterable[str | os.PathLike[str]] = (),
    ) -> None:
        self.root = _absolute(root)
        self.configuration = configuration
        self.application_paths = application_paths or resolve_application_paths()
        self.protected_paths = tuple(protected_paths)

    @classmethod
    def from_configuration(
        cls,
        configuration: ApplicationConfiguration,
        *,
        application_paths: ApplicationPaths | None = None,
        protected_paths: Iterable[str | os.PathLike[str]] = (),
    ) -> PublicationStore:
        paths = application_paths or resolve_application_paths()
        root = resolve_publication_root(configuration.storage.publish, paths)
        return cls(
            root,
            configuration=configuration,
            application_paths=paths,
            protected_paths=protected_paths,
        )

    def _validate_root(self) -> Path:
        protected_paths = list(self.protected_paths)
        standard_root = Path(self.application_paths.publish_directory)
        if self.root != standard_root:
            protected_paths.append(standard_root)
        if self.configuration is not None and self.configuration.storage.publish is not None:
            configured_root = Path(self.configuration.storage.publish)
            if self.root != configured_root:
                protected_paths.append(configured_root)
        self.root = validate_publication_root(
            self.root,
            protected_paths=protected_paths,
            application_paths=self.application_paths,
            configuration=self.configuration,
        )
        return self.root

    @staticmethod
    def _destination_id(value: object) -> str:
        if not isinstance(value, str) or not _valid_destination_identifier(value):
            raise PublicationStorageError(
                "destination_id must match [A-Za-z0-9][A-Za-z0-9_-]* and be at most 256 characters"
            )
        return value

    def _destination(self, destination_id: str, *, create: bool) -> Path:
        self._validate_root()
        if create:
            _create_directory(self.root)
        destination = self.root / destination_id
        if destination.parent != self.root:
            raise PublicationStorageError("destination directory must be a direct child of the publication root")
        _check_path_components(destination)
        try:
            status = destination.lstat()
        except FileNotFoundError:
            if not create:
                raise PublicationStorageError(f"publication destination does not exist: {destination}")
            try:
                destination.mkdir()
            except OSError as error:
                raise PublicationStorageError(
                    f"cannot create publication destination {destination}: {error}"
                ) from error
            _check_path_components(destination)
            return destination
        except OSError as error:
            raise PublicationStorageError(f"cannot inspect publication destination {destination}: {error}") from error
        if _is_redirect(destination, status):
            raise PublicationStorageError(f"refusing to use a linked publication destination: {destination}")
        if not stat.S_ISDIR(status.st_mode):
            raise PublicationStorageError(f"publication destination is not a directory: {destination}")
        return destination

    @staticmethod
    def _manifest_path(destination: Path) -> Path:
        return destination / "manifest.json"

    def _ensure_destination_ownership(self, destination: Path) -> None:
        marker = destination / ".refrain-owned"
        try:
            status = marker.lstat()
        except FileNotFoundError:
            try:
                children = tuple(destination.iterdir())
            except OSError as error:
                raise PublicationStorageError(
                    f"cannot inspect publication destination {destination}: {error}"
                ) from error
            if children:
                try:
                    current = self._load_current(destination)
                except PublicationStorageError as error:
                    raise PublicationStorageError(
                        f"cannot adopt unmarked publication destination {destination}: {error}"
                    ) from error
                if current is None:
                    raise PublicationStorageError(
                        f"cannot adopt nonempty unmarked publication destination {destination}"
                    )
            self._write_bytes(marker, b"")
            _sync_directory(destination)
            return
        except OSError as error:
            raise PublicationStorageError(f"cannot inspect publication ownership marker {marker}: {error}") from error
        if _is_redirect(marker, status) or not stat.S_ISREG(status.st_mode) or status.st_size != 0:
            raise PublicationStorageError(f"invalid publication ownership marker: {marker}")

    def _load_current(self, destination: Path) -> PublicationDataset | None:
        manifest_path = self._manifest_path(destination)
        try:
            manifest_status = manifest_path.lstat()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise PublicationStorageError(
                f"cannot inspect current publication manifest {manifest_path}: {error}"
            ) from error
        if _is_redirect(manifest_path, manifest_status) or not stat.S_ISREG(manifest_status.st_mode):
            raise PublicationStorageError(f"current publication manifest is not a regular file: {manifest_path}")
        manifest_bytes = _read_regular_file(manifest_path, limit=_MAX_MANIFEST_BYTES)
        manifest = parse_publication_manifest(manifest_bytes)
        dataset = self._read_dataset(destination, manifest)
        if _read_regular_file(manifest_path, limit=_MAX_MANIFEST_BYTES) != manifest_bytes:
            raise PublicationStorageError("publication manifest changed during dataset verification")
        return dataset

    def _read_dataset(self, destination: Path, manifest: PublicationManifest) -> PublicationDataset:
        image_path = destination / manifest.image_filename
        metadata_path = destination / manifest.metadata_filename
        image = _read_regular_file(image_path)
        metadata_bytes = _read_regular_file(metadata_path, limit=_MAX_METADATA_BYTES)
        if hashlib.sha256(image).hexdigest() != manifest.image_sha256:
            raise PublicationStorageError(f"publication image hash does not match the manifest: {image_path}")
        if hashlib.sha256(metadata_bytes).hexdigest() != manifest.metadata_sha256:
            raise PublicationStorageError(f"publication metadata hash does not match the manifest: {metadata_path}")
        try:
            metadata = parse_publication_metadata(metadata_bytes, stage="completed")
        except ValueError as error:
            raise PublicationStorageError(f"current publication metadata is invalid: {error}") from error
        self._validate_association(metadata, manifest.publication_id, destination.name)
        publication = metadata["publication"]
        assert isinstance(publication, dict)
        output = publication["output_specification"]
        assert isinstance(output, dict)
        expected_size = tuple(output["requested_output_size"])
        _matches_image(image, expected_size)
        return PublicationDataset(manifest, image, metadata)

    @staticmethod
    def _validate_association(metadata: Mapping[str, object], publication_id: str, destination_id: str) -> None:
        publication = metadata.get("publication")
        if not isinstance(publication, Mapping):
            raise PublicationStorageError("completed publication metadata has no publication object")
        if publication.get("id") != publication_id:
            raise PublicationStorageError("publication metadata ID does not match the dataset identity")
        if publication.get("destination_id") != destination_id:
            raise PublicationStorageError("publication metadata destination does not match its owning directory")

    def read_current(self, destination_id: str) -> PublicationDataset:
        """Read and verify the current publication using only its manifest and files."""
        destination_id = self._destination_id(destination_id)
        destination = self._destination(destination_id, create=False)
        last_error: PublicationStorageError | None = None
        for _attempt in range(2):
            try:
                dataset = self._load_current(destination)
            except PublicationStorageError as error:
                last_error = error
                continue
            if dataset is not None:
                return dataset
        if last_error is not None:
            raise last_error
        raise PublicationStorageError(f"publication manifest is missing: {self._manifest_path(destination)}")

    def _write_bytes(self, path: Path, contents: bytes) -> None:
        with _open_exclusive(path) as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())

    def _write_image(self, path: Path, image: Image.Image) -> None:
        with _open_exclusive(path) as output:
            image.save(output, format="PNG")
            output.flush()
            os.fsync(output.fileno())

    @staticmethod
    def _replace_manifest(temporary: Path, manifest_path: Path) -> None:
        os.replace(temporary, manifest_path)

    @staticmethod
    def _generated_name(name: str) -> bool:
        return _generated_publication_name(name)

    def _cleanup_contents(self, destination: Path, keep: set[str]) -> None:
        root = self._validate_root()
        if destination.parent != root:
            raise PublicationStorageError("publication cleanup target must be a direct child of the publication root")
        _check_path_components(destination)
        try:
            destination_status = destination.lstat()
            marker = destination / ".refrain-owned"
            marker_status = marker.lstat()
        except OSError as error:
            raise PublicationStorageError(f"cannot inspect publication destination {destination}: {error}") from error
        if _is_redirect(destination, destination_status) or not stat.S_ISDIR(destination_status.st_mode):
            raise PublicationStorageError(f"refusing to clean an unsafe publication destination: {destination}")
        if _is_redirect(marker, marker_status) or not stat.S_ISREG(marker_status.st_mode) or marker_status.st_size:
            raise PublicationStorageError(f"invalid publication ownership marker: {marker}")
        keep = keep | {".refrain-owned"}
        try:
            if os.name == "nt":
                self._cleanup_windows_directory(destination, keep)
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(destination, flags)
                try:
                    if not os.path.samestat(destination_status, os.fstat(descriptor)):
                        raise PublicationStorageError(f"publication destination changed during cleanup: {destination}")
                    current_marker = os.stat(".refrain-owned", dir_fd=descriptor, follow_symlinks=False)
                    if not os.path.samestat(marker_status, current_marker) or current_marker.st_size:
                        raise PublicationStorageError(f"publication ownership marker changed during cleanup: {marker}")
                    self._cleanup_directory_fd(descriptor, destination, destination_status.st_dev, keep)
                finally:
                    os.close(descriptor)
        except OSError as error:
            raise PublicationStorageError(f"cannot clean publication destination {destination}: {error}") from error

    def _cleanup_directory_fd(self, descriptor: int, directory: Path, device: int, keep: set[str]) -> None:
        with os.scandir(descriptor) as entries:
            names = [entry.name for entry in entries if entry.name not in keep]
        for name in names:
            child = directory / name
            status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(status.st_mode):
                os.unlink(name, dir_fd=descriptor)
            elif stat.S_ISDIR(status.st_mode):
                if status.st_dev != device or os.path.ismount(child):
                    raise PublicationStorageError(f"refusing to traverse a mounted publication object: {child}")
                flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                child_fd = os.open(name, flags, dir_fd=descriptor)
                try:
                    if not os.path.samestat(status, os.fstat(child_fd)):
                        raise PublicationStorageError(f"publication directory changed during cleanup: {child}")
                    self._cleanup_directory_fd(child_fd, child, device, set())
                finally:
                    os.close(child_fd)
                os.rmdir(name, dir_fd=descriptor)
            elif stat.S_ISREG(status.st_mode):
                os.unlink(name, dir_fd=descriptor)
            else:
                raise PublicationStorageError(f"refusing to clean an unsafe publication object: {child}")

    def _cleanup_windows_directory(self, directory: Path, keep: set[str]) -> None:
        raise PublicationStorageError(
            f"cannot safely clean publication destination {directory}: "
            "handle-relative, non-following cleanup is unavailable on Windows"
        )

    def publish(
        self,
        destination_id: str,
        image: Image.Image,
        metadata: Mapping[str, object],
        *,
        audience: str | None = None,
    ) -> PublicationManifest:
        """Atomically publish a complete image and already-finalized metadata dataset."""
        destination_id = self._destination_id(destination_id)
        if not isinstance(image, Image.Image):
            raise PublicationStorageError("publication image must be a Pillow image")
        if not isinstance(metadata, dict):
            raise PublicationStorageError("publication metadata must be a completed metadata mapping")
        try:
            validate_publication_metadata(metadata, stage="completed", audience=audience)
            metadata_bytes = serialize_publication_metadata(metadata, stage="completed", audience=audience).encode(
                "utf-8"
            )
        except (ValueError, TypeError, RecursionError) as error:
            raise PublicationStorageError(f"completed publication metadata is invalid: {error}") from error

        publication = metadata["publication"]
        assert isinstance(publication, dict)
        publication_id = publication.get("id")
        if (
            not isinstance(publication_id, str)
            or not _PUBLICATION_ID.fullmatch(publication_id)
            or publication_id.casefold() == "manifest"
            or publication_id.upper() in _WINDOWS_RESERVED_DESTINATION_IDS
        ):
            raise PublicationStorageError(
                "publication_id must be a valid filename identifier of at most 240 characters"
            )
        self._validate_association(metadata, publication_id, destination_id)
        output_specification = publication["output_specification"]
        assert isinstance(output_specification, dict)
        expected_size = tuple(output_specification["requested_output_size"])
        if image.size != expected_size:
            raise PublicationStorageError("publication image dimensions do not match completed metadata")

        destination = self._destination(destination_id, create=True)
        self._ensure_destination_ownership(destination)
        try:
            previous_names = {child.name for child in destination.iterdir()}
        except OSError as error:
            raise PublicationStorageError(f"cannot inspect publication destination {destination}: {error}") from error
        manifest_path = self._manifest_path(destination)
        previous_manifest = _manifest_snapshot(manifest_path)
        try:
            current = self._load_current(destination)
        except PublicationStorageError:
            # Ownership permits replacement of an invalid dataset; preserve it until commit.
            current = None
        if _manifest_snapshot(manifest_path) != previous_manifest:
            raise PublicationStorageError("publication manifest changed while preparing the replacement")
        if current is not None:
            if current.manifest.publication_id.casefold() == publication_id.casefold():
                raise PublicationStorageError("publication_id must identify a new publication event")

        image_filename = f"{publication_id}.png"
        metadata_filename = f"{publication_id}.json"
        image_path = destination / image_filename
        metadata_path = destination / metadata_filename
        existing_names = {child.name.casefold() for child in destination.iterdir()}
        if image_filename.casefold() in existing_names or metadata_filename.casefold() in existing_names:
            raise PublicationStorageError("publication output filename already exists; choose a unique publication_id")
        temporary_manifest = destination / f".refrain-{uuid.uuid4().hex}.manifest.tmp"
        committed_manifest: bytes | None = None
        replacement_started = False
        try:
            self._write_image(image_path, image)
            self._write_bytes(metadata_path, metadata_bytes)
            image_bytes = _read_regular_file(image_path)
            _matches_image(image_bytes, expected_size)
            manifest = PublicationManifest(
                publication_id,
                image_filename,
                metadata_filename,
                hashlib.sha256(image_bytes).hexdigest(),
                hashlib.sha256(metadata_bytes).hexdigest(),
            )
            committed_manifest = serialize_publication_manifest(manifest)
            self._write_bytes(temporary_manifest, committed_manifest)
            _sync_directory(destination)
            replacement_started = True
            self._replace_manifest(temporary_manifest, self._manifest_path(destination))
        except Exception as error:
            committed = False
            if replacement_started and committed_manifest is not None:
                try:
                    current_manifest = _manifest_snapshot(manifest_path)
                    proposed_manifest = (len(committed_manifest), hashlib.sha256(committed_manifest).hexdigest())
                    if current_manifest == proposed_manifest:
                        verified = self.read_current(destination_id)
                        committed = verified.manifest == manifest
                        if not committed:
                            raise PublicationStorageError("replacement dataset does not match the proposed publication")
                    elif current_manifest != previous_manifest:
                        raise PublicationStorageError(
                            "current manifest is neither the previous nor proposed publication"
                        )
                except PublicationStorageError as verification_error:
                    raise PublicationStorageError(
                        f"publication commit outcome is uncertain; retaining all files for safe recovery: "
                        f"{verification_error}",
                        published=True,
                    ) from error
            if not committed:
                try:
                    self._cleanup_contents(destination, previous_names)
                except PublicationStorageError as cleanup_error:
                    raise PublicationStorageError(
                        f"publication failed before manifest commit: {error}; "
                        f"temporary cleanup also failed: {cleanup_error}"
                    ) from error
                raise PublicationStorageError(f"publication failed before manifest commit: {error}") from error
            _LOGGER.warning("Publication %s was committed despite a replacement error: %s", publication_id, error)

        try:
            verified = self.read_current(destination_id)
            if verified.manifest != manifest:
                raise PublicationStorageError("committed publication does not match the proposed dataset")
        except PublicationStorageError as error:
            raise PublicationStorageError(
                f"publication commit outcome is uncertain; retaining all files for safe recovery: {error}",
                published=True,
            ) from error

        try:
            _sync_directory(destination)
            self._cleanup_contents(destination, {".refrain-owned", "manifest.json", image_filename, metadata_filename})
            _sync_directory(destination)
        except PublicationStorageError as error:
            _LOGGER.warning(
                "Publication %s committed successfully but obsolete-file cleanup failed; retry cleanup: %s",
                publication_id,
                error,
            )
        return manifest

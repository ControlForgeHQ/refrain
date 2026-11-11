"""Durable, hardware-independent storage of revision-scoped prepared images."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from PIL import Image

from .geometry import ResolvedOutputSpecification
from .renderer import CompositionVisibility

_MODES = {"1", "L", "LA", "RGB", "RGBA"}
_REVISION = re.compile(r"revision-([1-9][0-9]*)\Z")
_TEMPORARY = re.compile(r"\.tmp-revision-[1-9][0-9]*-[0-9a-f]{32}\Z")
_PAYLOAD = re.compile(r"images-[0-9a-f]{32}\Z")
_VARIANT_DIRECTORY = re.compile(r"variant-[0-9]+-[0-9]+-[1-9][0-9]*x[1-9][0-9]*\Z")
_STAGE = re.compile(r"stage-(0|[1-9][0-9]*)\.png\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ArtifactStoreError(Exception):
    """Base class for prepared-image storage failures."""


class ArtifactValidationError(ArtifactStoreError):
    """An existing artifact set is incomplete, damaged, or mismatched."""


class ArtifactAccessError(ArtifactStoreError):
    """The artifact root cannot be accessed or is not a usable directory."""


class ArtifactWriteError(ArtifactStoreError):
    """A write failed; ``published`` identifies whether the manifest was replaced."""

    def __init__(self, message: str, *, published: bool = False) -> None:
        self.published = published
        super().__init__(message)


class ArtifactCleanupError(ArtifactStoreError):
    """Cleanup failed; already published artifacts remain independent of cleanup."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _positive_integer(value: object, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _stage_definitions(stages: Sequence[CompositionVisibility]) -> list[dict[str, bool]]:
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise ValueError("stages must be a nonempty sequence of CompositionVisibility values")
    if any(not isinstance(stage, CompositionVisibility) for stage in stages):
        raise ValueError("stages must contain only CompositionVisibility values")
    return [
        {
            "quotation": stage.quotation,
            "source": stage.source,
            "attribution": stage.attribution,
        }
        for stage in stages
    ]


def _inputs(revision: int, stages: Sequence[CompositionVisibility]) -> list[dict[str, bool]]:
    _positive_integer(revision, "revision")
    return _stage_definitions(stages)


def _output_specifications(
    specifications: Sequence[ResolvedOutputSpecification],
) -> tuple[ResolvedOutputSpecification, ...]:
    if not isinstance(specifications, Sequence) or isinstance(specifications, (str, bytes)) or not specifications:
        raise ValueError("output_specifications must be a nonempty sequence of ResolvedOutputSpecification values")
    if any(not isinstance(specification, ResolvedOutputSpecification) for specification in specifications):
        raise ValueError("output_specifications must contain only ResolvedOutputSpecification values")
    if len(set(specifications)) != len(specifications):
        raise ValueError("output_specifications must not contain equivalent duplicates")
    return tuple(sorted(specifications, key=lambda item: (item.aspect_ratio, *item.requested_output_size)))


def _variant_directory_name(specification: ResolvedOutputSpecification) -> str:
    aspect = specification.aspect_ratio.replace(":", "-")
    width, height = specification.requested_output_size
    return f"variant-{aspect}-{width}x{height}"


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _require_directory(path: Path) -> None:
    if _is_link(path) or not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError(f"{path} must be a real directory, not a link")


def _require_file(path: Path) -> None:
    if _is_link(path) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"{path} must be a regular file, not a link")


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_directories(path: Path) -> None:
    if path.parent != path:
        _create_directories(path.parent)
    if path.exists():
        _require_directory(path)
    else:
        path.mkdir()
    _sync_directory(path.parent)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True)
class PreparedImageArtifactVariant:
    """Validated metadata for one output specification.

    ``presentation_canvas_literary_bounds`` uses presentation-canvas coordinates
    and is not scaled to the requested output-image dimensions. Close returned stages after use.
    """

    output_specification: ResolvedOutputSpecification
    mode: str
    stage_paths: tuple[Path, ...]
    _digests: tuple[str, ...]
    presentation_canvas_literary_bounds: tuple[int, int, int, int] | None = field(
        default=None, compare=False, repr=False
    )

    @property
    def requested_output_size(self) -> tuple[int, int]:
        """Return the exact persisted output raster dimensions."""
        return self.output_specification.requested_output_size

    def load_stage(self, stage: int) -> Image.Image:
        """Decode one independent image, rechecking integrity since initial validation."""
        if type(stage) is not int or not 0 <= stage < len(self.stage_paths):
            raise ValueError(f"stage must be an integer from 0 to {len(self.stage_paths) - 1}")
        path = self.stage_paths[stage]
        try:
            for directory in (path.parent, *path.parent.parents):
                _require_directory(directory)
            _require_file(path)
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != self._digests[stage]:
                    raise ValueError("PNG checksum does not match manifest")
                stream.seek(0)
                with Image.open(stream) as image:
                    if image.format != "PNG" or image.size != self.requested_output_size or image.mode != self.mode:
                        raise ValueError(
                            f"expected PNG size {self.requested_output_size} mode {self.mode}; "
                            f"found {image.format} size {image.size} mode {image.mode}"
                        )
                    if getattr(image, "n_frames", 1) != 1:
                        raise ValueError("stage must contain exactly one complete image")
                    image.verify()
                stream.seek(0)
                image = Image.open(stream)
                try:
                    image.load()
                except BaseException:
                    image.close()
                    raise
                return image
        except FileNotFoundError as error:
            raise ArtifactValidationError(f"invalid prepared stage {path}: {error}") from error
        except OSError as error:
            if error.errno is not None:
                raise ArtifactAccessError(f"cannot access prepared stage {path}: {error}") from error
            raise ArtifactValidationError(f"invalid prepared stage {path}: {error}") from error
        except (ValueError, SyntaxError, Image.DecompressionBombError) as error:
            raise ArtifactValidationError(f"invalid prepared stage {path}: {error}") from error


@dataclass(frozen=True)
class PreparedImageArtifactSet:
    """Validated metadata for a coherent revision-scoped set of raster variants."""

    revision: int
    directory: Path
    variants: Mapping[ResolvedOutputSpecification, PreparedImageArtifactVariant]

    @property
    def output_specifications(self) -> tuple[ResolvedOutputSpecification, ...]:
        """Return the ordered identities represented by this coherent artifact set."""
        return tuple(self.variants)

    def variant_for(self, output_specification: ResolvedOutputSpecification) -> PreparedImageArtifactVariant:
        """Return metadata for one exact output specification."""
        try:
            return self.variants[output_specification]
        except KeyError:
            raise ValueError(f"artifact set does not contain output specification {output_specification!r}") from None

    def load_stage(self, output_specification: ResolvedOutputSpecification, stage: int) -> Image.Image:
        """Decode one stage of one raster variant."""
        return self.variant_for(output_specification).load_stage(stage)


class PreparedImageArtifactStore:
    """Own derived PNG artifacts under an absolute root; callers serialize operations.

    ``load`` returns ``None`` only for an absent revision directory. Existing but
    invalid sets raise ``ArtifactValidationError``. No operation regenerates images.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise ValueError("artifact root must be an absolute path without '..'")

    def _check_root(self) -> None:
        for path in (*reversed(self.root.parents), self.root):
            try:
                status = path.lstat()
            except FileNotFoundError:
                continue
            if _is_link(path):
                raise ValueError(f"artifact root cannot traverse a symbolic link or junction: {path}")
            if not stat.S_ISDIR(status.st_mode):
                raise ValueError(f"{path} must be a real directory, not a link")

    def store(
        self,
        revision: int,
        stages: Sequence[CompositionVisibility],
        variants: Mapping[ResolvedOutputSpecification, Sequence[Image.Image]],
    ) -> PreparedImageArtifactSet:
        """Publish all explicit variants and stages losslessly; inputs remain caller-owned."""
        expected_stages = _inputs(revision, stages)
        if not isinstance(variants, Mapping) or not variants:
            raise ValueError("variants must be a nonempty mapping of output specifications to image sequences")
        specifications = _output_specifications(tuple(variants))
        images_by_specification: dict[ResolvedOutputSpecification, tuple[Image.Image, ...]] = {}
        for specification in specifications:
            images = variants[specification]
            if not isinstance(images, Sequence) or isinstance(images, (str, bytes)) or not images:
                raise ValueError(f"images for {specification!r} must be a nonempty sequence of complete Pillow images")
            if len(images) != len(expected_stages):
                raise ValueError(f"images for {specification!r} must match the expected reveal-stage sequence")
            requested_output_size = specification.requested_output_size
            mode = images[0].mode if isinstance(images[0], Image.Image) else None
            for index, image in enumerate(images):
                if (
                    not isinstance(image, Image.Image)
                    or image.size != requested_output_size
                    or image.mode not in _MODES
                ):
                    raise ValueError(
                        f"stage {index} for {specification!r} must be a Pillow image of size "
                        f"{requested_output_size} in a supported mode"
                    )
                if image.mode != mode:
                    raise ValueError(f"all stages for {specification!r} must use the same image mode")
            images_by_specification[specification] = tuple(images)

        directory = self.root / f"revision-{revision}"
        token = uuid.uuid4().hex
        temporary = self.root / f".tmp-revision-{revision}-{token}"
        payload = directory / f"images-{token}"
        published = False
        try:
            self._check_root()
            _create_directories(self.root)
            _create_directories(directory)
            temporary.mkdir()
            variant_metadata = []
            stored_variants = {}
            for specification in specifications:
                images = images_by_specification[specification]
                variant_directory_name = _variant_directory_name(specification)
                variant_directory = temporary / variant_directory_name
                variant_directory.mkdir()
                digests = []
                for index, image in enumerate(images):
                    path = variant_directory / f"stage-{index}.png"
                    with path.open("xb") as stream:
                        image.save(stream, format="PNG")
                        stream.flush()
                        os.fsync(stream.fileno())
                    with path.open("rb") as stream:
                        digests.append(hashlib.file_digest(stream, "sha256").hexdigest())
                variant_metadata.append(
                    {
                        "aspect_ratio": specification.aspect_ratio,
                        "requested_output_size": list(specification.requested_output_size),
                        "mode": images[0].mode,
                        "stages": [
                            {"visibility": visibility, "sha256": digest}
                            for visibility, digest in zip(expected_stages, digests)
                        ],
                    }
                )
                stored_variants[specification] = PreparedImageArtifactVariant(
                    specification,
                    images[0].mode,
                    tuple(payload / variant_directory_name / f"stage-{i}.png" for i in range(len(images))),
                    tuple(digests),
                )
            metadata = {
                "revision": revision,
                "image_directory": payload.name,
                "variants": variant_metadata,
            }
            document = {"artifacts": metadata, "sha256": hashlib.sha256(_canonical_json(metadata)).hexdigest()}
            with (temporary / "manifest.json").open("xb") as stream:
                stream.write(_canonical_json(document) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            for specification in specifications:
                _sync_directory(temporary / _variant_directory_name(specification))
            _sync_directory(temporary)
            os.replace(temporary, payload)
            _sync_directory(self.root)
            _sync_directory(directory)
            os.replace(payload / "manifest.json", directory / "manifest.json")
            published = True
            for specification in specifications:
                _sync_directory(payload / _variant_directory_name(specification))
            _sync_directory(payload)
            _sync_directory(directory)
        except (OSError, ValueError) as error:
            status = (
                "complete set published; directory durability unconfirmed; reload before retry"
                if published
                else "prior manifest unchanged"
            )
            raise ArtifactWriteError(
                f"cannot store prepared images at {directory}: {error}; {status}", published=published
            ) from error
        return PreparedImageArtifactSet(revision, directory, MappingProxyType(stored_variants))

    def load(
        self,
        revision: int,
        stages: Sequence[CompositionVisibility],
        output_specifications: Sequence[ResolvedOutputSpecification],
    ) -> PreparedImageArtifactSet | None:
        """Validate a whole expected set sequentially, retaining no decoded images."""
        expected_stages = _inputs(revision, stages)
        expected_specifications = _output_specifications(output_specifications)
        stage_count = len(expected_stages)
        directory = self.root / f"revision-{revision}"
        try:
            self._check_root()
            root_exists = _exists(self.root)
            directory_exists = _exists(directory) if root_exists else False
        except (OSError, ValueError) as error:
            raise ArtifactAccessError(f"cannot access prepared-image root {self.root}: {error}") from error
        if not root_exists or not directory_exists:
            return None
        try:
            _require_directory(directory)
            manifest = directory / "manifest.json"
            _require_file(manifest)
            document = json.loads(manifest.read_bytes(), object_pairs_hook=_unique_object)
            if not isinstance(document, dict) or set(document) != {"artifacts", "sha256"}:
                raise ValueError("manifest must contain artifacts and sha256")
            metadata = document["artifacts"]
            fields = {"revision", "image_directory", "variants"}
            if not isinstance(metadata, dict) or set(metadata) != fields:
                raise ValueError("manifest artifact fields are missing or unsupported")
            if document["sha256"] != hashlib.sha256(_canonical_json(metadata)).hexdigest():
                raise ValueError("manifest checksum does not match")
            if type(metadata["revision"]) is not int or metadata["revision"] != revision:
                raise ValueError("manifest revision does not match expected committed revision")
            name = metadata["image_directory"]
            if not isinstance(name, str) or not _PAYLOAD.fullmatch(name):
                raise ValueError("invalid manifest image_directory")
            payload = directory / name
            _require_directory(payload)
            variants = metadata["variants"]
            if not isinstance(variants, list) or len(variants) != len(expected_specifications):
                raise ValueError(f"manifest must contain exactly {len(expected_specifications)} output variants")
            if {path.name for path in payload.iterdir()} != {
                _variant_directory_name(specification) for specification in expected_specifications
            }:
                raise ValueError("image directory does not contain exactly the expected output variants")
            loaded_variants = {}
            for variant_index, (variant, expected_specification) in enumerate(zip(variants, expected_specifications)):
                if (
                    not isinstance(variant, dict)
                    or set(variant) != {"aspect_ratio", "requested_output_size", "mode", "stages"}
                    or not isinstance(variant["aspect_ratio"], str)
                    or not isinstance(variant["requested_output_size"], list)
                    or len(variant["requested_output_size"]) != 2
                    or any(type(value) is not int or value <= 0 for value in variant["requested_output_size"])
                    or not isinstance(variant["mode"], str)
                    or variant["mode"] not in _MODES
                ):
                    raise ValueError(f"manifest variant {variant_index} has malformed output metadata")
                specification = ResolvedOutputSpecification(
                    variant["aspect_ratio"], tuple(variant["requested_output_size"])
                )
                if specification != expected_specification:
                    raise ValueError(f"manifest variant {variant_index} does not match expected output specification")
                variant_stages = variant["stages"]
                if not isinstance(variant_stages, list) or len(variant_stages) != stage_count:
                    raise ValueError(f"manifest variant {variant_index} must contain exactly {stage_count} stages")
                digests = []
                for stage_index, stage in enumerate(variant_stages):
                    if (
                        not isinstance(stage, dict)
                        or set(stage) != {"visibility", "sha256"}
                        or stage["visibility"] != expected_stages[stage_index]
                        or not isinstance(stage["sha256"], str)
                        or not _DIGEST.fullmatch(stage["sha256"])
                    ):
                        raise ValueError(
                            f"manifest variant {variant_index} stage {stage_index} "
                            "has invalid visibility or checksum"
                        )
                    digests.append(stage["sha256"])
                variant_directory = payload / _variant_directory_name(specification)
                _require_directory(variant_directory)
                paths = tuple(variant_directory / f"stage-{i}.png" for i in range(stage_count))
                if {path.name for path in variant_directory.iterdir()} != {path.name for path in paths}:
                    raise ValueError(
                        f"image directory for variant {variant_index} does not contain exactly the expected stages"
                    )
                loaded_variants[specification] = PreparedImageArtifactVariant(
                    specification, variant["mode"], paths, tuple(digests)
                )
            result = PreparedImageArtifactSet(revision, directory, MappingProxyType(loaded_variants))
            for specification in expected_specifications:
                variant = result.variant_for(specification)
                for index in range(stage_count):
                    with variant.load_stage(index):
                        pass
            return result
        except FileNotFoundError as error:
            raise ArtifactValidationError(f"invalid prepared images at {directory}: {error}") from error
        except OSError as error:
            raise ArtifactAccessError(f"cannot access prepared images at {directory}: {error}") from error
        except (ValueError, RecursionError) as error:
            raise ArtifactValidationError(f"invalid prepared images at {directory}: {error}") from error

    def cleanup(self, current_revision: int) -> None:
        """Remove recognized stale directories and abandoned root-level transactions.

        Preserve the current directory even when invalid. Unknown entries and trees
        containing links are left untouched. Callers must exclude concurrent users.
        """
        _positive_integer(current_revision, "current_revision")
        try:
            self._check_root()
            if not self.root.exists():
                return
            _require_directory(self.root)
            for path in self.root.iterdir():
                revision = _REVISION.fullmatch(path.name)
                temporary = _TEMPORARY.fullmatch(path.name)
                if not revision and not temporary:
                    continue
                if revision and int(revision[1]) == current_revision:
                    if _is_link(path) or not path.is_dir():
                        continue
                    active_payload = _manifest_payload(path, current_revision)
                    if active_payload is not None:
                        for candidate in path.iterdir():
                            if (
                                candidate.name == active_payload
                                or not _PAYLOAD.fullmatch(candidate.name)
                                or _is_link(candidate)
                                or not candidate.is_dir()
                                or not _owned_tree(candidate, payload=True)
                            ):
                                continue
                            shutil.rmtree(candidate)
                            _sync_directory(path)
                    continue
                if _is_link(path) or not path.is_dir():
                    continue
                if _owned_tree(path, payload=bool(temporary)):
                    shutil.rmtree(path)
                    _sync_directory(self.root)
        except (OSError, ValueError) as error:
            raise ArtifactCleanupError(f"cannot clean prepared images under {self.root}: {error}") from error


def _owned_tree(directory: Path, *, payload: bool) -> bool:
    for path in directory.iterdir():
        if _is_link(path):
            return False
        if path.is_file() and (path.name == "manifest.json" or _STAGE.fullmatch(path.name)):
            continue
        if not payload and _PAYLOAD.fullmatch(path.name) and path.is_dir() and _owned_tree(path, payload=True):
            continue
        if payload and _VARIANT_DIRECTORY.fullmatch(path.name) and path.is_dir() and _owned_tree(path, payload=False):
            continue
        return False
    return True


def _manifest_payload(directory: Path, revision: int) -> str | None:
    """Return the active owned payload only when its manifest association is intact."""
    manifest = directory / "manifest.json"
    try:
        _require_file(manifest)
        document = json.loads(manifest.read_bytes(), object_pairs_hook=_unique_object)
        if not isinstance(document, dict) or set(document) != {"artifacts", "sha256"}:
            return None
        metadata = document["artifacts"]
        if not isinstance(metadata, dict) or set(metadata) != {
            "revision",
            "image_directory",
            "variants",
        }:
            return None
        if document["sha256"] != hashlib.sha256(_canonical_json(metadata)).hexdigest():
            return None
        if type(metadata["revision"]) is not int or metadata["revision"] != revision:
            return None
        name = metadata["image_directory"]
        if not isinstance(name, str) or not _PAYLOAD.fullmatch(name):
            return None
        _require_directory(directory / name)
        return name
    except FileNotFoundError:
        return None
    except OSError:
        raise
    except (ValueError, RecursionError, TypeError):
        return None

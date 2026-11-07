"""Discovery and validation of packaged presentation assets."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import TypeVar

import yaml
from PIL import Image, ImageFont

from ._yaml import load_yaml

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z", re.ASCII)
_FONT_ROLES = {"quotation", "source", "attribution"}
_T = TypeVar("_T")
AssetPath = Path | Traversable
Report = Callable[[str, str, int], None]


def valid_identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def parse_font_faces(value: object, field: str, report: Report) -> Mapping[str, str]:
    if not isinstance(value, dict):
        report(
            field,
            "must be a mapping of literary roles to face identifiers; preferences are ignored",
            logging.WARNING,
        )
        return MappingProxyType({})
    result: dict[str, str] = {}
    valid = True
    for role, face in value.items():
        role_field = f"{field}.{role}" if isinstance(role, str) else f"{field}[{role!r}]"
        if not isinstance(role, str) or role not in _FONT_ROLES:
            report(role_field, "is not a supported literary role; preferences are ignored", logging.WARNING)
            valid = False
        elif not valid_identifier(face):
            report(
                role_field,
                "must be a nonempty ASCII face identifier; preferences are ignored",
                logging.WARNING,
            )
            valid = False
        else:
            result[role] = face
    return MappingProxyType(result if valid else {})


def _parse_decoration_color(value: object, field: str, report: Report) -> tuple[str, ...] | None:
    if isinstance(value, str):
        if value:
            return (value,)
        report(field, "must be a palette identifier or nonempty sequence of identifiers; preference is ignored")
        return None
    if not isinstance(value, list) or not value:
        report(field, "must be a palette identifier or nonempty sequence of identifiers; preference is ignored")
        return None
    result: list[str] = []
    for index, identifier in enumerate(value):
        if isinstance(identifier, str):
            result.append(identifier)
        else:
            report(
                f"{field}[{index}]",
                "must be a palette identifier; this preference member is ignored",
                logging.WARNING,
            )
    return tuple(result) or None


def _is_link(path: AssetPath) -> bool:
    return isinstance(path, Path) and path.is_symlink()


def _children(path: AssetPath, report: Report | None = None, category: str = "assets") -> list[AssetPath]:
    try:
        return sorted(path.iterdir(), key=lambda item: item.name)
    except (OSError, NotImplementedError) as error:
        if report is not None and isinstance(error, OSError):
            report(f"assets.{category}.{path}", f"cannot inspect asset directory: {error}", logging.WARNING)
        return []


def _exists(path: AssetPath) -> bool:
    try:
        return path.is_file()
    except (OSError, NotImplementedError):
        return False


def _walk_packages(
    root: AssetPath, manifest: str, report: Report, category: str
) -> Iterable[tuple[AssetPath, AssetPath]]:
    def visit(directory: AssetPath):
        if _is_link(directory):
            return
        manifest_path = directory.joinpath(manifest)
        if not _is_link(manifest_path) and _exists(manifest_path):
            yield directory, manifest_path
            return
        for child in _children(directory, report, category):
            if _is_link(child):
                continue
            if child.is_dir():
                yield from visit(child)

    if not _is_link(root) and root.is_dir():
        yield from visit(root)


def _read_manifest(path: AssetPath) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        value = load_yaml(stream.read())
    if not isinstance(value, dict):
        raise ValueError("manifest must contain a mapping")
    return value


def _manifest_path(package: AssetPath, value: object, formats: set[str]) -> AssetPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("resource path must be a nonempty relative path")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("resource path must be relative")
    if "\\" in value:
        raise ValueError("resource path must use forward slashes")
    if ".." in posix_path.parts:
        raise ValueError("resource path must remain within its asset package")
    if posix_path.suffix.lower() not in formats or not posix_path.parts:
        raise ValueError(f"resource path must use one of: {', '.join(sorted(formats))}")
    candidate = package.joinpath(*posix_path.parts)
    if isinstance(package, Path) and isinstance(candidate, Path):
        try:
            package_root = package.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(package_root)
        except (OSError, ValueError) as error:
            raise ValueError("resource path is missing or resolves outside its asset package") from error
        candidate = resolved
    elif not _exists(candidate):
        raise ValueError("resource file does not exist")
    if not _exists(candidate):
        raise ValueError("resource file does not exist")
    return candidate


def _unknown_fields(data: Mapping[str, object], allowed: set[str], field: str, report: Report) -> None:
    for key in sorted(data.keys() - allowed):
        report(f"{field}.{key}", "is not a supported manifest field; it is ignored", logging.WARNING)


def _parse_manifest(
    manifest_path: AssetPath,
    category: str,
    allowed: set[str],
    report: Report,
) -> tuple[AssetPath, dict[str, object]] | None:
    field = str(manifest_path)
    try:
        data = _read_manifest(manifest_path)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
        report(field, f"manifest is invalid and the asset is excluded: {error}", logging.WARNING)
        return None
    _unknown_fields(data, allowed, field, report)
    if type(data.get("format")) is not int or data.get("format") != 1:
        report(
            f"{field}.format",
            "must be the supported integer manifest version 1; the asset is excluded",
            logging.WARNING,
        )
        return None
    identifier = data.get("id")
    if not valid_identifier(identifier):
        report(f"{field}.id", "must be a nonempty ASCII identifier; the asset is excluded", logging.WARNING)
        return None
    image = data.get("image")
    try:
        image_path = _manifest_path(manifest_path.parent, image, {".png"})
    except (OSError, ValueError) as error:
        report(f"{field}.image", f"is invalid; the asset is excluded: {error}", logging.WARNING)
        return None
    return image_path, data


def _font_validation_error(path: AssetPath) -> str | None:
    try:
        with path.open("rb") as stream:
            ImageFont.truetype(stream, size=12)
    except Exception as error:
        return str(error)
    return None


def _validate_image_metadata(path: AssetPath, category: str) -> None:
    image_kind = category.removesuffix("s")
    with path.open("rb") as stream:
        with Image.open(stream) as image:
            if image.format != "PNG":
                raise ValueError(f"{image_kind} must be a PNG image")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError(f"{image_kind} must be a single-frame PNG image")
            if image_kind == "background" and image.mode not in {"RGB", "RGBA"}:
                raise ValueError("background mode must be RGB or RGBA")
            if image_kind == "decoration" and image.mode != "RGBA":
                raise ValueError("decoration mode must be RGBA")
            if image.width <= 0 or image.height <= 0:
                raise ValueError(f"{image_kind} dimensions must be positive")
            image.verify()


def _validate_candidate(
    resource: _T,
    identifier: str,
    bundled: bool,
    reserved: set[str],
    candidates: list[tuple[str, _T, bool, str]],
    location: str,
    report: Report,
    field: str,
) -> None:
    if bundled and identifier not in reserved:
        report(
            field, f"bundled identifier {identifier!r} is not a reserved public identifier; excluded", logging.WARNING
        )
        return
    candidates.append((identifier, resource, bundled, location))


def _register_candidates(
    candidates: list[tuple[str, _T, bool, str]],
    reserved: set[str],
    category: str,
    report: Report,
) -> dict[str, _T]:
    bundled: dict[str, _T] = {}
    custom: dict[str, list[tuple[_T, str]]] = defaultdict(list)
    for identifier, resource, is_bundled, location in candidates:
        if is_bundled:
            if identifier in bundled:
                report(
                    f"assets.{category}.{identifier}",
                    f"duplicate bundled identifier at {location}; excluded",
                    logging.WARNING,
                )
            else:
                bundled[identifier] = resource
        else:
            custom[identifier].append((resource, location))
    result = dict(bundled)
    for identifier in sorted(custom):
        entries = custom[identifier]
        if identifier in reserved or identifier in bundled:
            for _, location in entries:
                report(
                    f"assets.{category}.{identifier}",
                    f"custom asset at {location} conflicts with reserved bundled identifier {identifier!r}; excluded",
                    logging.WARNING,
                )
        elif len(entries) > 1:
            locations = ", ".join(sorted(location for _, location in entries))
            report(
                f"assets.{category}.{identifier}",
                f"custom assets at {locations} share identifier {identifier!r}; all are excluded",
                logging.WARNING,
            )
        else:
            result[identifier] = entries[0][0]
    return result


def discover_backgrounds(
    bundled_root: AssetPath,
    custom_root: Path,
    reserved: set[str],
    report: Report,
) -> dict[str, object]:
    from .config import BackgroundResource

    candidates: list[tuple[str, BackgroundResource, bool, str]] = []

    def scan(root: AssetPath, is_bundled: bool) -> None:
        def visit(directory: AssetPath) -> None:
            if _is_link(directory):
                return
            manifest = directory.joinpath("background.yaml")
            if not _is_link(manifest) and _exists(manifest):
                parsed = _parse_manifest(manifest, "background", {"format", "id", "image"}, report)
                if parsed is not None:
                    image_path, data = parsed
                    identifier = data["id"]
                    resource = BackgroundResource(identifier, image_path, is_bundled)
                    _validate_image_candidate(
                        resource,
                        identifier,
                        is_bundled,
                        reserved,
                        candidates,
                        str(manifest),
                        report,
                        "background",
                    )
                return
            for child in _children(directory, report, "backgrounds"):
                if _is_link(child):
                    continue
                if child.is_dir():
                    visit(child)
                elif child.name.lower().endswith(".png"):
                    identifier = Path(child.name).stem
                    resource = BackgroundResource(identifier, child, is_bundled)
                    _validate_image_candidate(
                        resource,
                        identifier,
                        is_bundled,
                        reserved,
                        candidates,
                        str(child),
                        report,
                        "background",
                    )

        if root.is_dir() and not _is_link(root):
            visit(root)

    scan(bundled_root, True)
    scan(custom_root, False)
    return _register_candidates(candidates, reserved, "backgrounds", report)


def _validate_image_candidate(
    resource: _T,
    identifier: object,
    is_bundled: bool,
    reserved: set[str],
    candidates: list[tuple[str, _T, bool, str]],
    location: str,
    report: Report,
    category: str,
) -> None:
    field = f"assets.{category}.{identifier}"
    if not valid_identifier(identifier):
        report(field, f"identifier {identifier!r} is invalid; asset at {location} is excluded", logging.WARNING)
        return
    if identifier == "none":
        report(
            field, f"reserved identifier 'none' cannot be registered; asset at {location} is excluded", logging.WARNING
        )
        return
    try:
        _validate_image_metadata(resource.path, category)  # type: ignore[attr-defined]
    except Exception as error:
        report(field, f"asset at {location} is unreadable or invalid and is excluded: {error}", logging.WARNING)
        return
    _validate_candidate(resource, identifier, is_bundled, reserved, candidates, location, report, field)


def discover_decorations(
    bundled_root: AssetPath,
    custom_root: Path,
    reserved: set[str],
    font_ids: set[str],
    background_ids: set[str],
    report: Report,
    parse_region: Callable[..., object],
) -> dict[str, object]:
    from .config import DecorationResource

    candidates: list[tuple[str, DecorationResource, bool, str]] = []
    for root, is_bundled in ((bundled_root, True), (custom_root, False)):
        for package, manifest in _walk_packages(root, "decoration.yaml", report, "decorations"):
            field = str(manifest)
            parsed = _parse_manifest(
                manifest,
                "decoration",
                {
                    "format",
                    "id",
                    "image",
                    "presentation_region",
                    "font",
                    "font_faces",
                    "background",
                    "text_color",
                    "tintable",
                    "decoration_color",
                },
                report,
            )
            if parsed is None:
                continue
            image_path, data = parsed
            identifier = data["id"]
            region = None
            if "presentation_region" in data:
                region = parse_region(
                    data["presentation_region"], f"{field}.presentation_region", report, logging.WARNING
                )
                if region is None:
                    report(f"{field}.presentation_region", "is invalid; this decoration is excluded", logging.WARNING)
                    continue
            preferred_font = data.get("font")
            if "font" in data and (not valid_identifier(preferred_font) or preferred_font not in font_ids):
                report(
                    f"{field}.font",
                    f"font preference {preferred_font!r} is unavailable or invalid; ignored",
                    logging.WARNING,
                )
                preferred_font = None
            font_faces = (
                parse_font_faces(data["font_faces"], f"{field}.font_faces", report)
                if "font_faces" in data
                else MappingProxyType({})
            )
            preferred_background = data.get("background")
            if "background" in data and (
                not valid_identifier(preferred_background)
                or (preferred_background != "none" and preferred_background not in background_ids)
            ):
                report(
                    f"{field}.background",
                    f"background preference {preferred_background!r} is unavailable or invalid; ignored",
                    logging.WARNING,
                )
                preferred_background = None
            preferred_text_color = (
                _parse_decoration_color(data["text_color"], f"{field}.text_color", report)
                if "text_color" in data
                else None
            )
            preferred_decoration_color = (
                _parse_decoration_color(data["decoration_color"], f"{field}.decoration_color", report)
                if "decoration_color" in data
                else None
            )
            tintable = data.get("tintable", False)
            if "tintable" in data and type(tintable) is not bool:
                report(f"{field}.tintable", "must be a YAML boolean; tinting is disabled", logging.WARNING)
                tintable = False
            resource = DecorationResource(
                identifier=identifier,
                path=image_path,
                bundled=is_bundled,
                presentation_region=region,  # type: ignore[arg-type]
                font=preferred_font,
                font_faces=font_faces,
                background=preferred_background,
                text_color=preferred_text_color,
                tintable=tintable,
                decoration_color=preferred_decoration_color,
            )
            _validate_image_candidate(
                resource,
                identifier,
                is_bundled,
                reserved,
                candidates,
                field,
                report,
                "decorations",
            )
    return _register_candidates(candidates, reserved, "decorations", report)


def discover_fonts(
    bundled_root: AssetPath,
    custom_root: Path,
    reserved: set[str],
    report: Report,
) -> dict[str, object]:
    from .config import FontResource

    candidates: list[tuple[str, FontResource, bool, str]] = []
    for root, is_bundled in ((bundled_root, True), (custom_root, False)):
        for package, manifest in _walk_packages(root, "font.yaml", report, "fonts"):
            field = str(manifest)
            try:
                data = _read_manifest(manifest)
            except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
                report(field, f"manifest is invalid and the font bundle is excluded: {error}", logging.WARNING)
                continue
            _unknown_fields(data, {"format", "id", "faces", "font_faces"}, field, report)
            if type(data.get("format")) is not int or data.get("format") != 1:
                report(
                    f"{field}.format",
                    "must be the supported integer manifest version 1; bundle excluded",
                    logging.WARNING,
                )
                continue
            identifier = data.get("id")
            if not valid_identifier(identifier):
                report(f"{field}.id", "must be a nonempty ASCII identifier; bundle excluded", logging.WARNING)
                continue
            faces = data.get("faces")
            if not isinstance(faces, dict) or not faces:
                report(
                    f"{field}.faces",
                    "must be a nonempty mapping of face names to font paths; bundle excluded",
                    logging.WARNING,
                )
                continue
            if "regular" not in faces:
                report(f"{field}.faces.regular", "a usable regular face is required; bundle excluded", logging.WARNING)
                continue
            face_paths: dict[str, AssetPath] = {}
            invalid_structure = False
            for face, face_value in sorted(faces.items(), key=lambda pair: str(pair[0])):
                face_field = f"{field}.faces.{face}"
                if not valid_identifier(face):
                    report(
                        face_field, "face name must be a nonempty ASCII identifier; bundle excluded", logging.WARNING
                    )
                    invalid_structure = True
            if invalid_structure:
                continue
            invalid_regular = False
            for face, face_value in sorted(faces.items(), key=lambda pair: str(pair[0])):
                face_field = f"{field}.faces.{face}"
                try:
                    face_path = _manifest_path(package, face_value, {".ttf", ".otf"})
                except (OSError, ValueError) as error:
                    report(face_field, f"font path is invalid and this face is excluded: {error}", logging.WARNING)
                    invalid_regular |= face == "regular"
                    continue
                font_error = _font_validation_error(face_path)
                if font_error is not None:
                    report(
                        face_field,
                        f"font file is unreadable or unsupported by Pillow and this face is excluded: {font_error}",
                        logging.WARNING,
                    )
                    invalid_regular |= face == "regular"
                    continue
                face_paths[face] = face_path
            if invalid_regular or "regular" not in face_paths:
                report(f"{field}.faces.regular", "a usable regular face is required; bundle excluded", logging.WARNING)
                continue
            font_faces = (
                parse_font_faces(data["font_faces"], f"{field}.font_faces", report)
                if "font_faces" in data
                else MappingProxyType({})
            )
            resource = FontResource(
                identifier=identifier,
                path=face_paths["regular"],
                bundled=is_bundled,
                faces=MappingProxyType(face_paths),
                font_faces=font_faces,
            )
            if identifier == "none":
                report(
                    f"{field}.id", "reserved identifier 'none' cannot be registered; bundle excluded", logging.WARNING
                )
                continue
            _validate_candidate(resource, identifier, is_bundled, reserved, candidates, field, report, field)
    return _register_candidates(candidates, reserved, "fonts", report)


__all__ = ["discover_backgrounds", "discover_decorations", "discover_fonts", "parse_font_faces", "valid_identifier"]

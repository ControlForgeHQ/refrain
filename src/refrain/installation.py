"""Explicit, non-destructive installation initialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Callable, TextIO

from .config import ApplicationConfigurationError, load_application_config
from .content import ContentLibraryError, load_content_library
from .paths import ApplicationPaths


class InitializationError(Exception):
    """Raised when initialization cannot safely install the packaged defaults."""


class InstallationOperationError(Exception):
    """Raised when a standard installation operation cannot safely complete."""


_SAMPLE_INSTALL_MARKER = ".refrain-initialize-samples.json"


def _packaged_resources() -> tuple[bytes, dict[PurePosixPath, bytes]]:
    try:
        package = files("refrain")
        configuration = package.joinpath("config.default.yaml").read_bytes()
        content = package.joinpath("sample_content")
        if not content.is_dir():
            raise InitializationError("the packaged sample content directory is unavailable")
        entries: dict[PurePosixPath, bytes] = {}

        def collect(directory, relative: PurePosixPath) -> None:
            for item in sorted(directory.iterdir(), key=lambda resource: resource.name):
                child = relative / item.name
                if item.is_dir():
                    collect(item, child)
                elif item.is_file() and Path(item.name).suffix.lower() in {".yaml", ".yml"}:
                    entries[child] = item.read_bytes()

        collect(content, PurePosixPath())
        if not entries:
            raise InitializationError("the packaged sample content library is empty")
        if PurePosixPath(_SAMPLE_INSTALL_MARKER) in entries:
            raise InitializationError(
                f"the packaged sample library uses the reserved filename {_SAMPLE_INSTALL_MARKER}"
            )
        return configuration, entries
    except InitializationError:
        raise
    except Exception as error:
        raise InitializationError(f"cannot read packaged defaults: {error}") from error


def _validate_resources(configuration: bytes, content_entries: dict[PurePosixPath, bytes]) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="refrain-initialize-validation-") as temporary:
            root = Path(temporary)
            config_file = root / "config.yaml"
            config_file.write_bytes(configuration)
            load_application_config(config_file)
            content_directory = root / "content"
            for relative, contents in content_entries.items():
                target = content_directory.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
            entries = load_content_library(content_directory)
            if not any(rule.ordinary for entry in entries for rule in entry.eligibility):
                raise InitializationError("the packaged sample content has no ordinary eligible quotations")
    except InitializationError:
        raise
    except (ApplicationConfigurationError, ContentLibraryError, OSError, ValueError) as error:
        raise InitializationError(f"packaged defaults failed validation: {error}") from error


def _is_link(path: Path, status: os.stat_result | None = None) -> bool:
    if path.is_symlink() or path.is_junction():
        return True
    status = path.lstat() if status is None else status
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(status, "st_file_attributes", 0) & reparse_point)


def _inspect_directory(path: Path) -> bool:
    """Return whether a real directory exists, rejecting unsafe objects in its path."""
    for candidate in reversed((path, *path.parents)):
        try:
            status = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise InstallationOperationError(f"cannot inspect installation destination {candidate}: {error}") from error
        if _is_link(candidate, status):
            raise InstallationOperationError(f"refusing to follow a filesystem link at {candidate}")
        if candidate == path:
            if not stat.S_ISDIR(status.st_mode):
                raise InstallationOperationError(f"required directory is not a directory: {candidate}")
            return True
        if not stat.S_ISDIR(status.st_mode):
            raise InstallationOperationError(f"required parent is not a directory: {candidate}")
    return False


def _inspect_file(path: Path) -> bool:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise InstallationOperationError(f"cannot inspect installation destination {path}: {error}") from error
    if _is_link(path, status):
        raise InstallationOperationError(f"refusing to use a filesystem link at {path}")
    if not stat.S_ISREG(status.st_mode):
        raise InstallationOperationError(f"expected a regular file at {path}")
    return True


def _content_is_empty(directory: Path) -> bool:
    try:
        return next(directory.iterdir(), None) is None
    except OSError as error:
        raise InitializationError(f"cannot inspect content directory {directory}: {error}") from error


def _sample_install_manifest(content_entries: dict[PurePosixPath, bytes]) -> bytes:
    manifest = {
        "format": 1,
        "files": {
            relative.as_posix(): hashlib.sha256(contents).hexdigest()
            for relative, contents in sorted(content_entries.items(), key=lambda item: str(item[0]))
        },
    }
    return (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _resume_sample_installation(content_directory: Path, content_entries: dict[PurePosixPath, bytes]) -> bool:
    marker = content_directory / _SAMPLE_INSTALL_MARKER
    if not _inspect_file(marker):
        return False
    try:
        marker_contents = marker.read_bytes()
    except OSError as error:
        raise InitializationError(f"cannot read interrupted sample-install marker {marker}: {error}") from error
    if marker_contents != _sample_install_manifest(content_entries):
        raise InitializationError(
            f"cannot establish ownership of the nonempty content directory {content_directory}; "
            f"the sample-install marker {marker} is invalid or does not match the packaged samples. "
            "Preserve or inspect the files manually before retrying."
        )

    for relative, contents in content_entries.items():
        target = content_directory.joinpath(*relative.parts)
        try:
            parent = content_directory
            for component in relative.parts[:-1]:
                parent = parent / component
                _inspect_directory(parent)
            if _inspect_file(target) and target.read_bytes() != contents:
                raise InitializationError(
                    f"cannot safely resume sample installation because existing content differs from "
                    f"the packaged sample: {target}. Preserve or inspect the files manually."
                )
        except InstallationOperationError as error:
            raise InitializationError(f"cannot safely resume sample installation: {error}") from error
        except OSError as error:
            raise InitializationError(f"cannot inspect sample destination {target}: {error}") from error
    return True


def _create_directory(path: Path, created: list[Path], owned_directories: set[Path]) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        if path.parent != path:
            _create_directory(path.parent, created, owned_directories)
        path.mkdir()
        created.append(path)
        return
    except OSError as error:
        raise OSError(f"cannot inspect directory {path}: {error}") from error
    if _is_link(path):
        raise OSError(f"refusing to follow a filesystem link while creating {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"required parent is not a directory: {path}")


def _create_file(path: Path, contents: bytes, created: list[Path], owned_directories: set[Path]) -> None:
    parent = path.parent
    while parent in owned_directories:
        if _is_link(parent) or not parent.is_dir():
            raise OSError(f"refusing to write through an unexpected content directory: {parent}")
        parent = parent.parent
    with path.open("xb") as output:
        created.append(path)
        output.write(contents)


def initialize_installation(
    paths: ApplicationPaths,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, ...]:
    """Install packaged defaults at standard locations without replacing any destination."""
    report = progress or (lambda message: None)
    configuration, content_entries = _packaged_resources()
    _validate_resources(configuration, content_entries)

    directories = tuple(
        Path(path)
        for path in (
            paths.config_directory,
            paths.content_directory,
            paths.operational_directory,
            paths.state_directory,
            paths.cache_directory,
            paths.artifacts_directory,
        )
    )
    try:
        existing_directories = {directory for directory in directories if _inspect_directory(directory)}
        configuration_exists = _inspect_file(Path(paths.config_file))
        _inspect_file(Path(paths.state_file))
        _inspect_file(Path(paths.history_file))
        content_directory = Path(paths.content_directory)
        resume_samples = (
            _resume_sample_installation(content_directory, content_entries)
            if content_directory in existing_directories
            else False
        )
        install_samples = (
            resume_samples or content_directory not in existing_directories or _content_is_empty(content_directory)
        )
    except InstallationOperationError as error:
        raise InitializationError(f"initialization cannot safely use the installation paths: {error}") from error

    created: list[Path] = []
    try:
        config_directory = Path(paths.config_directory)
        content_directories = (
            {content_directory.joinpath(*relative.parts).parent for relative in content_entries}
            if install_samples
            else set()
        )
        owned_directories = {
            Path(paths.config_directory),
            Path(paths.content_directory),
            Path(paths.operational_directory),
            Path(paths.state_directory),
            Path(paths.cache_directory),
            Path(paths.artifacts_directory),
            *content_directories,
        }
        _create_directory(config_directory, created, owned_directories)
        _create_directory(content_directory, created, owned_directories)
        if not configuration_exists:
            _create_file(Path(paths.config_file), configuration, created, owned_directories)
        if install_samples:
            marker = content_directory / _SAMPLE_INSTALL_MARKER
            if not resume_samples:
                _create_file(marker, _sample_install_manifest(content_entries), created, owned_directories)
            for directory in sorted(content_directories, key=lambda value: (len(value.parts), str(value))):
                if directory != content_directory:
                    _create_directory(directory, created, owned_directories)
            for relative, contents in sorted(content_entries.items(), key=lambda item: str(item[0])):
                target = content_directory.joinpath(*relative.parts)
                try:
                    target_exists = _inspect_file(target)
                except InstallationOperationError as error:
                    raise OSError(f"cannot safely use sample destination {target}: {error}") from error
                if target_exists:
                    try:
                        matches_packaged_sample = target.read_bytes() == contents
                    except OSError as error:
                        raise OSError(f"cannot read sample destination {target}: {error}") from error
                    if not matches_packaged_sample:
                        raise FileExistsError(f"sample destination contains different content: {target}")
                else:
                    _create_file(target, contents, created, owned_directories)
            marker.unlink()
            if marker in created:
                created.remove(marker)
        _create_directory(Path(paths.state_directory), created, owned_directories)
        _create_directory(Path(paths.artifacts_directory), created, owned_directories)
    except OSError as error:
        created_paths = "\n".join(f"  {path}" for path in created) or "  (none)"
        raise InitializationError(
            f"initialization failed: {error}\nCreated destinations that remain in place:\n{created_paths}"
        ) from error

    report(f"Configuration: {paths.config_file}")
    if configuration_exists:
        report(f"Existing configuration preserved: {paths.config_file}")
    report(f"Content: {paths.content_directory}")
    if not install_samples:
        report(
            f"Existing nonempty content directory preserved; packaged samples not installed: {paths.content_directory}"
        )
    report(f"State directory: {paths.state_directory}")
    report(f"Artifacts: {paths.artifacts_directory}")
    return tuple(created)


def confirm_operation(
    confirmation: str,
    description: str,
    paths: tuple[Path, ...],
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    """Require exact confirmation from an interactive terminal."""
    input_stream = sys.stdin if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    print(description, file=output_stream)
    print("Affected standard Refrain locations:", file=output_stream)
    for path in paths:
        print(f"  {path}", file=output_stream)
    if not input_stream.isatty() or not output_stream.isatty():
        print("An interactive terminal is required; no changes were made.", file=output_stream)
        return False
    print(f"Type {confirmation!r} to continue: ", end="", flush=True, file=output_stream)
    response = input_stream.readline()
    if response.endswith("\n"):
        response = response[:-1]
    if response.endswith("\r"):
        response = response[:-1]
    if response != confirmation:
        print("Confirmation did not match; operation cancelled. No changes were made.", file=output_stream)
        return False
    return True


def _remove_leaf(path: Path, status: os.stat_result) -> None:
    if _is_link(path, status):
        if path.is_junction() or (
            os.name == "nt"
            and bool(getattr(status, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            and stat.S_ISDIR(status.st_mode)
        ):
            path.rmdir()
        else:
            path.unlink()
    elif stat.S_ISDIR(status.st_mode):
        raise InstallationOperationError(f"refusing to remove unexpected directory where a file is expected: {path}")
    else:
        path.unlink()


def _remove_tree(path: Path, *, root: bool = False) -> None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise InstallationOperationError(f"cannot inspect {path}: {error}") from error
    if _is_link(path, status):
        if root:
            raise InstallationOperationError(f"refusing to remove linked installation directory {path}")
        try:
            _remove_leaf(path, status)
        except OSError as error:
            raise InstallationOperationError(f"cannot remove filesystem link {path}: {error}") from error
        return
    if stat.S_ISDIR(status.st_mode):
        try:
            for child in path.iterdir():
                _remove_tree(child)
            path.rmdir()
        except OSError as error:
            raise InstallationOperationError(f"cannot remove directory {path}: {error}") from error
        return
    if root:
        raise InstallationOperationError(f"expected an installation directory at {path}")
    try:
        path.unlink()
    except OSError as error:
        raise InstallationOperationError(f"cannot remove {path}: {error}") from error


def _remove_expected_file(path: Path) -> None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise InstallationOperationError(f"cannot inspect {path}: {error}") from error
    if not _is_link(path, status) and not stat.S_ISREG(status.st_mode):
        raise InstallationOperationError(f"expected a regular file or filesystem link at {path}")
    try:
        _remove_leaf(path, status)
    except OSError as error:
        raise InstallationOperationError(f"cannot remove {path}: {error}") from error


def reset_installation(paths: ApplicationPaths) -> None:
    """Remove standard runtime state, history, and generated cache contents."""
    state_directory = Path(paths.state_directory)
    cache_directory = Path(paths.cache_directory)
    artifacts_directory = Path(paths.artifacts_directory)
    state_exists = _inspect_directory(state_directory)
    cache_exists = _inspect_directory(cache_directory)
    artifacts_exists = _inspect_directory(artifacts_directory)

    state_files: list[Path] = []
    if state_exists:
        state_files.extend((Path(paths.state_file), Path(paths.history_file)))
        try:
            for candidate in state_directory.iterdir():
                if re.fullmatch(r"global-history\.\d+\.jsonl", candidate.name):
                    state_files.append(candidate)
        except OSError as error:
            raise InstallationOperationError(f"cannot inspect history directory {state_directory}: {error}") from error
        for path in state_files:
            try:
                status = path.lstat()
            except FileNotFoundError:
                continue
            except OSError as error:
                raise InstallationOperationError(f"cannot inspect {path}: {error}") from error
            if not _is_link(path, status) and not stat.S_ISREG(status.st_mode):
                raise InstallationOperationError(f"expected a regular file or filesystem link at {path}")
        for path in state_files:
            _remove_expected_file(path)

    if cache_exists:
        try:
            for child in cache_directory.iterdir():
                if child == artifacts_directory:
                    if artifacts_exists:
                        for artifact in child.iterdir():
                            _remove_tree(artifact)
                else:
                    _remove_tree(child)
        except OSError as error:
            raise InstallationOperationError(
                f"cannot clear generated cache under {cache_directory}: {error}"
            ) from error


def purge_installation(paths: ApplicationPaths) -> tuple[Path, ...]:
    """Remove the complete standard Refrain installation without crossing linked paths."""
    candidates = tuple(
        dict.fromkeys(
            Path(path) for path in (paths.config_directory, paths.operational_directory, paths.cache_directory)
        )
    )
    roots = tuple(
        candidate
        for candidate in candidates
        if not any(candidate != other and candidate.is_relative_to(other) for other in candidates)
    )
    for root in roots:
        try:
            _inspect_directory(root)
        except InstallationOperationError:
            raise
    for root in roots:
        _remove_tree(root, root=True)
    return roots

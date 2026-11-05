"""Explicit, non-destructive installation initialization."""

from __future__ import annotations

import tempfile
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Callable

from .config import ApplicationConfigurationError, load_application_config
from .content import ContentLibraryError, load_content_library
from .paths import ApplicationPaths


class InitializationError(Exception):
    """Raised when initialization cannot safely install the packaged defaults."""


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


def _existing_targets(paths: ApplicationPaths) -> tuple[Path, ...]:
    targets = (
        paths.config_directory,
        paths.config_file,
        paths.content_directory,
        paths.operational_directory,
        paths.state_directory,
        paths.state_file,
        paths.history_file,
        paths.cache_directory,
        paths.artifacts_directory,
    )
    existing: list[Path] = []
    for target in dict.fromkeys(targets):
        path = Path(target)
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except NotADirectoryError:
            blocker = path.parent
            while blocker != blocker.parent:
                try:
                    blocker.lstat()
                except (FileNotFoundError, NotADirectoryError):
                    blocker = blocker.parent
                    continue
                except OSError as error:
                    raise InitializationError(f"cannot inspect installation destination {blocker}: {error}") from error
                if not blocker.is_dir():
                    existing.append(blocker)
                break
            continue
        except OSError as error:
            raise InitializationError(f"cannot inspect installation destination {path}: {error}") from error
        existing.append(path)
    return tuple(dict.fromkeys(existing))


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
    if path in owned_directories and path not in created:
        raise FileExistsError(f"installation destination appeared during initialization: {path}")
    if path.is_symlink():
        raise OSError(f"refusing to follow a filesystem link while creating {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"required parent is not a directory: {path}")


def _create_file(path: Path, contents: bytes, created: list[Path], owned_directories: set[Path]) -> None:
    parent = path.parent
    while parent in owned_directories:
        if parent.is_symlink() or not parent.is_dir():
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

    conflicts = _existing_targets(paths)
    if conflicts:
        formatted = "\n".join(f"  {path}" for path in conflicts)
        raise InitializationError(
            "initialization refused because these destinations already exist:\n"
            f"{formatted}\n"
            "Inspect, move, or remove the conflicting data manually before retrying; no changes were made."
        )

    created: list[Path] = []
    try:
        config_directory = Path(paths.config_directory)
        content_directory = Path(paths.content_directory)
        content_directories = {content_directory.joinpath(*relative.parts).parent for relative in content_entries}
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
        _create_file(Path(paths.config_file), configuration, created, owned_directories)
        for directory in sorted(content_directories, key=lambda value: (len(value.parts), str(value))):
            if directory != content_directory:
                _create_directory(directory, created, owned_directories)
        for relative, contents in sorted(content_entries.items(), key=lambda item: str(item[0])):
            _create_file(content_directory.joinpath(*relative.parts), contents, created, owned_directories)
        _create_directory(Path(paths.state_directory), created, owned_directories)
        _create_directory(Path(paths.artifacts_directory), created, owned_directories)
    except OSError as error:
        created_paths = "\n".join(f"  {path}" for path in created) or "  (none)"
        raise InitializationError(
            f"initialization failed: {error}\nCreated destinations that remain in place:\n{created_paths}"
        ) from error

    report(f"Configuration: {paths.config_file}")
    report(f"Content: {paths.content_directory}")
    report(f"State directory: {paths.state_directory}")
    report(f"Artifacts: {paths.artifacts_directory}")
    return tuple(created)

"""Resolve platform-standard per-user Refrain paths."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath
from typing import Mapping


class ApplicationPathError(Exception):
    """Raised when required per-user application locations are unavailable."""


@dataclass(frozen=True)
class ApplicationPaths:
    """Standard user installation and runtime locations."""

    config_directory: PurePath
    config_file: PurePath
    content_directory: PurePath
    operational_directory: PurePath
    state_directory: PurePath
    state_file: PurePath
    history_file: PurePath
    cache_directory: PurePath
    artifacts_directory: PurePath

    @property
    def ownership_file(self) -> PurePath:
        """Lock metadata outside the standard Refrain installation trees."""
        return self.operational_directory.parent / ".refrain-ownership.lock"

    @property
    def assets_directory(self) -> PurePath:
        """Standard user-owned assets beside the per-user configuration."""
        return self.config_directory / "assets"

    @property
    def asset_directories(self) -> tuple[PurePath, ...]:
        """Standard category directories for user-owned visual resources."""
        return tuple(self.assets_directory / category for category in ("fonts", "backgrounds", "decorations"))


def _absolute_path(value: str, path_type: type[PurePath], name: str) -> PurePath:
    path = path_type(value)
    if not path.is_absolute():
        raise ApplicationPathError(f"{name} must be an absolute path, not {value!r}")
    return path


def _home_directory(home: str | os.PathLike[str] | None, path_type: type[PurePath]) -> PurePath:
    try:
        value = os.fspath(home) if home is not None else str(Path.home())
    except (OSError, RuntimeError) as error:
        raise ApplicationPathError(f"cannot determine the per-user home directory: {error}") from error
    return _absolute_path(value, path_type, "the per-user home directory")


def resolve_application_paths(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> ApplicationPaths:
    """Resolve standard paths, with injectable platform inputs for deterministic tests."""
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ

    if platform.startswith("linux"):
        path_type: type[PurePath] = Path
        home_directory: PurePath | None = None

        def xdg_directory(variable: str, fallback: str) -> PurePath:
            nonlocal home_directory
            value = environ.get(variable, "")
            if value:
                try:
                    return _absolute_path(value, path_type, variable)
                except ApplicationPathError:
                    pass
            base = home_directory
            if base is None:
                base = _home_directory(home, path_type)
                home_directory = base
            return base / fallback

        config_base = xdg_directory("XDG_CONFIG_HOME", ".config")
        state_base = xdg_directory("XDG_STATE_HOME", ".local/state")
        cache_base = xdg_directory("XDG_CACHE_HOME", ".cache")
        config_directory = config_base / "refrain"
        operational_directory = state_base / "refrain"
        state_directory = operational_directory
        cache_directory = cache_base / "refrain"
        artifacts_directory = cache_directory / "artifacts"
    elif platform == "win32":
        path_type = Path if os.name == "nt" else PureWindowsPath
        roaming_value = environ.get("APPDATA", "")
        local_value = environ.get("LOCALAPPDATA", "")
        if not roaming_value or not path_type(roaming_value).is_absolute():
            raise ApplicationPathError("APPDATA must contain an absolute per-user roaming application-data path")
        if not local_value or not path_type(local_value).is_absolute():
            raise ApplicationPathError("LOCALAPPDATA must contain an absolute per-user local application-data path")
        roaming = path_type(roaming_value)
        local = path_type(local_value)
        config_directory = roaming / "Refrain"
        operational_directory = local / "Refrain"
        state_directory = operational_directory / "State"
        cache_directory = operational_directory / "Cache"
        artifacts_directory = cache_directory / "artifacts"
    elif platform == "darwin":
        path_type = Path
        home_directory = _home_directory(home, path_type)
        support = home_directory / "Library" / "Application Support" / "Refrain"
        config_directory = support
        operational_directory = support
        state_directory = operational_directory / "State"
        cache_directory = home_directory / "Library" / "Caches" / "Refrain"
        artifacts_directory = cache_directory / "artifacts"
    else:
        raise ApplicationPathError(f"standard per-user paths are not defined for platform {platform!r}")

    return ApplicationPaths(
        config_directory=config_directory,
        config_file=config_directory / "config.yaml",
        content_directory=config_directory / "content",
        operational_directory=operational_directory,
        state_directory=state_directory,
        state_file=state_directory / "state.json",
        history_file=state_directory / "global-history.jsonl",
        cache_directory=cache_directory,
        artifacts_directory=artifacts_directory,
    )

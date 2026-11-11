"""Command-line entry point for Refrain operation and installation management."""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import Event

from .application import ApplicationError, run_application, run_demo
from .config import ApplicationConfigurationError, load_application_config
from .installation import (
    InitializationError,
    InstallationOperationError,
    confirm_operation,
    initialize_installation,
    purge_installation,
    reset_installation,
)
from .ownership import InstallationOwnership, OwnershipError
from .paths import ApplicationPathError, ApplicationPaths, resolve_application_paths

_LOGGER = logging.getLogger(__name__)


def _installation_ownership(paths: ApplicationPaths) -> InstallationOwnership:
    ownership = InstallationOwnership()
    ownership.ensure_outside(
        (
            paths.config_directory,
            paths.content_directory,
            paths.assets_directory,
            *paths.asset_directories,
            paths.operational_directory,
            paths.state_directory,
            paths.cache_directory,
            paths.artifacts_directory,
            paths.state_file,
            paths.history_file,
        )
    )
    return ownership


def _demo_interval(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("demo interval must be a positive finite number of seconds") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("demo interval must be a positive finite number of seconds")
    return seconds


def _run_runtime(arguments: argparse.Namespace, paths: ApplicationPaths, ownership: InstallationOwnership) -> int:
    config_path = arguments.config if arguments.config is not None else paths.config_file
    config_absolute = Path(config_path).absolute()
    if not config_absolute.exists():
        _LOGGER.info("Effective configuration path: %s", config_absolute)
        print(
            f"refrain: configuration file does not exist: {config_absolute}\n"
            "Initialize the standard per-user configuration with `refrain --initialize`, "
            "or provide an existing file with --config.",
            file=sys.stderr,
        )
        return 1
    if arguments.demo is None:
        try:
            configuration = load_application_config(config_absolute)
        except ApplicationConfigurationError as error:
            raise ApplicationError(f"application configuration is invalid: {error}") from error
        state_path = Path(configuration.storage.state or paths.state_file).absolute()
        artifacts_path = Path(configuration.storage.artifacts or paths.artifacts_directory).absolute()
        history_path = Path(configuration.storage.history or paths.history_file).absolute()
        _LOGGER.info("Effective configuration path: %s", configuration.file)
        _LOGGER.info("Effective state path: %s", state_path)
        _LOGGER.info("Effective artifacts path: %s", artifacts_path)
        _LOGGER.info("Effective history path: %s", history_path)
    else:
        _LOGGER.info(
            "Effective configuration path: %s; %s",
            config_absolute,
            "demo persistence uses isolated temporary storage",
        )

    shutdown = Event()
    previous_handlers = {}
    try:
        for termination_signal in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[termination_signal] = signal.signal(
                termination_signal, lambda signum, frame: shutdown.set()
            )
        if arguments.demo is not None:
            run_demo(
                config_path,
                arguments.demo,
                shutdown_event=shutdown,
                pending_shutdown=ownership.defer_release_until,
            )
        else:
            run_application(
                configuration,
                state_path,
                artifacts_path,
                shutdown_event=shutdown,
                history_path=history_path,
                pending_shutdown=ownership.defer_release_until,
            )
    finally:
        for termination_signal, handler in previous_handlers.items():
            signal.signal(termination_signal, handler)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refrain",
        description="Present Refrain quotations and manage its installation.",
    )
    parser.add_argument("--config", help="application configuration YAML file")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--demo",
        type=_demo_interval,
        metavar="SECONDS",
        help="cycle canonical reveal stages at a positive finite interval using temporary session storage",
    )
    modes.add_argument(
        "--initialize",
        action="store_true",
        help="create missing standard installation resources without replacing existing data, then exit",
    )
    modes.add_argument(
        "--reset", action="store_true", help="remove standard runtime state and generated cache, then exit"
    )
    modes.add_argument(
        "--purge", action="store_true", help="remove the complete standard per-user installation, then exit"
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if arguments.initialize:
            if arguments.config is not None:
                parser.error("--initialize cannot be combined with --config")
            paths = resolve_application_paths()
            print("Initializing Refrain using the platform-standard per-user locations")
            with _installation_ownership(paths):
                initialize_installation(paths, progress=print)
            print("Initialization complete.")
            return 0

        if arguments.reset or arguments.purge:
            operation = "--reset" if arguments.reset else "--purge"
            if arguments.config is not None:
                parser.error(f"{operation} cannot be combined with --config")
            paths = resolve_application_paths()
            if arguments.reset:
                confirmed = confirm_operation(
                    "RESET",
                    "This removes operational state, global history, and generated cache data. "
                    "Configuration, content, and custom assets are preserved.",
                    (
                        Path(paths.state_file),
                        Path(paths.history_file),
                        Path(paths.state_directory),
                        Path(paths.cache_directory),
                        Path(paths.artifacts_directory),
                    ),
                )
                if not confirmed:
                    return 1
                with _installation_ownership(paths):
                    reset_installation(paths)
                print("Reset complete.")
            else:
                confirmed = confirm_operation(
                    "PURGE REFRAIN",
                    "WARNING: this permanently removes configuration, content, and user-provided files "
                    "within the standard Refrain locations, including custom fonts, backgrounds, and decorations "
                    "in the standard assets directory.",
                    tuple(
                        dict.fromkeys(
                            Path(path)
                            for path in (
                                paths.config_directory,
                                paths.content_directory,
                                paths.assets_directory,
                                *paths.asset_directories,
                                paths.operational_directory,
                                paths.state_directory,
                                paths.cache_directory,
                                paths.artifacts_directory,
                            )
                        )
                    ),
                )
                if not confirmed:
                    return 1
                with _installation_ownership(paths):
                    removed = purge_installation(paths)
                for path in removed:
                    print(f"Removed: {path}")
                print("Purge complete.")
            return 0

        paths = resolve_application_paths()
        with InstallationOwnership() as ownership:
            return _run_runtime(arguments, paths, ownership)
    except (
        ApplicationError,
        ApplicationPathError,
        InitializationError,
        InstallationOperationError,
        OwnershipError,
    ) as error:
        print(f"refrain: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

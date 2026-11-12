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
from .display.coordinator import PublicationResult, PublicationStatus
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
from .runtime_control import (
    RuntimeAuthenticationError,
    RuntimeControlClient,
    RuntimeControlError,
    RuntimeProtocolError,
    RuntimeUnavailable,
    RuntimeUnconfirmed,
    RuntimeUnsupportedProtocol,
)

_LOGGER = logging.getLogger(__name__)


def _installation_ownership(paths: ApplicationPaths) -> InstallationOwnership:
    ownership = InstallationOwnership(Path(paths.ownership_file))
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
        ownership.ensure_outside((state_path, artifacts_path, history_path))
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
                control_metadata_path=Path(paths.control_metadata_file),
            )
    finally:
        for termination_signal, handler in previous_handlers.items():
            signal.signal(termination_signal, handler)
    return 0


def _report_refresh_result(result: PublicationResult) -> int:
    if (
        result.status is PublicationStatus.SUCCEEDED
        and result.destinations
        and all(success is True for success, _error in result.destinations.values())
    ):
        print("Refresh completed successfully.")
        return 0

    messages = {
        PublicationStatus.BUSY: (
            "refresh was not accepted because publication is busy; wait for the current update to finish"
        ),
        PublicationStatus.FAILED: "refresh publication failed",
        PublicationStatus.STOPPING: "the resident Refrain runtime is stopping or rejected the refresh",
        PublicationStatus.INVALID: "the resident Refrain runtime rejected the refresh as invalid",
        PublicationStatus.UNSUPPORTED: "the resident Refrain runtime does not support refresh",
        PublicationStatus.WITHDRAWN: "a destination required by the refresh is intentionally withdrawn",
        PublicationStatus.DESTINATION_NOT_FOUND: "a destination required by the refresh is no longer configured",
    }
    message = messages.get(result.status, f"refresh ended with unexpected status {result.status.value!r}")
    print(f"refrain: {message}.", file=sys.stderr)
    for identifier, (success, error) in result.destinations.items():
        if success is not True:
            detail = error or ("publication failed" if success is False else "no terminal outcome reported")
            print(f"  {identifier}: {detail}", file=sys.stderr)
    return 1


def _run_refresh(paths: ApplicationPaths) -> int:
    def report_accepted() -> None:
        print("Refresh accepted; publication has begun.", flush=True)

    try:
        result = RuntimeControlClient(Path(paths.control_metadata_file)).refresh(on_accepted=report_accepted)
    except RuntimeUnconfirmed:
        print(
            "refrain: refresh outcome is unconfirmed; publication may have occurred. " "Do not retry automatically.",
            file=sys.stderr,
        )
        return 1
    except RuntimeUnavailable as error:
        print(f"refrain: {error}", file=sys.stderr)
        return 1
    except RuntimeAuthenticationError as error:
        print(
            f"refrain: {error}; restart the resident Refrain runtime for this user and try again.",
            file=sys.stderr,
        )
        return 1
    except RuntimeUnsupportedProtocol as error:
        print(
            f"refrain: {error}; ensure the client and resident runtime versions are compatible.",
            file=sys.stderr,
        )
        return 1
    except RuntimeProtocolError as error:
        print(
            f"refrain: runtime-control protocol error: {error}; restart the resident Refrain runtime.",
            file=sys.stderr,
        )
        return 1
    except RuntimeControlError as error:
        print(f"refrain: runtime-control request failed: {error}", file=sys.stderr)
        return 1
    return _report_refresh_result(result)


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
    modes.add_argument("--refresh", action="store_true", help="ask the running Refrain runtime to refresh its display")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if arguments.refresh:
            if arguments.config is not None:
                parser.error("--refresh cannot be combined with --config")
            paths = resolve_application_paths()
            return _run_refresh(paths)

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
        with _installation_ownership(paths) as ownership:
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

"""Command-line entry point for continuous and one-shot Refrain operation."""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import Event

from .application import ApplicationError, run_application, run_demo, run_startup
from .installation import InitializationError, initialize_installation
from .paths import ApplicationPathError, resolve_application_paths

_SERVING_BACKENDS = {"window", "image-server"}
_LOGGER = logging.getLogger(__name__)


def _hold_open(backend: str) -> None:
    if backend not in _SERVING_BACKENDS:
        return
    print("Display is active; press Ctrl+C to exit and release it.", file=sys.stderr)
    release = Event()
    try:
        while not release.wait(1):
            pass
    except KeyboardInterrupt:
        pass


def _demo_interval(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("demo interval must be a positive finite number of seconds") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("demo interval must be a positive finite number of seconds")
    return seconds


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="refrain", description="Run Refrain continuously until interrupted.")
    parser.add_argument("--config", help="application configuration YAML file")
    parser.add_argument("--state", help="persistent state file (ignored in demo mode)")
    parser.add_argument("--artifacts", help="prepared image directory (ignored in demo mode)")
    parser.add_argument(
        "--history", help="JSONL global-history file (default: global-history.jsonl beside state; ignored with --demo)"
    )
    parser.add_argument(
        "--history-segment-size",
        type=int,
        default=1_048_576,
        help="maximum global-history segment size in bytes (default: 1048576)",
    )
    parser.add_argument(
        "--history-max-segments",
        type=int,
        default=20,
        help="maximum retained global-history segments including the active segment (default: 20)",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="run one startup/presentation cycle without scheduling")
    modes.add_argument(
        "--demo",
        type=_demo_interval,
        metavar="SECONDS",
        help="cycle canonical reveal stages at a positive finite interval using temporary session storage",
    )
    modes.add_argument(
        "--initialize",
        action="store_true",
        help="install the packaged default configuration and sample content, then exit",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if arguments.initialize:
            overrides = [
                f"--{name}"
                for name in ("config", "state", "artifacts", "history")
                if getattr(arguments, name) is not None
            ]
            if overrides:
                parser.error("--initialize cannot be combined with path overrides: " + ", ".join(overrides))
            paths = resolve_application_paths()
            print("Initializing Refrain using the platform-standard per-user locations")
            initialize_installation(paths, progress=print)
            print("Initialization complete.")
            return 0

        paths = resolve_application_paths()
        config_path = arguments.config if arguments.config is not None else paths.config_file
        config_absolute = Path(config_path).absolute()
        if arguments.demo is None:
            state_path = arguments.state if arguments.state is not None else paths.state_file
            artifacts_path = arguments.artifacts if arguments.artifacts is not None else paths.artifacts_directory
            history_path = arguments.history
            effective_history = (
                Path(history_path).absolute()
                if history_path is not None
                else Path(state_path).absolute().with_name("global-history.jsonl")
            )
            _LOGGER.info("Effective configuration path: %s", config_absolute)
            _LOGGER.info("Effective state path: %s", Path(state_path).absolute())
            _LOGGER.info("Effective artifacts path: %s", Path(artifacts_path).absolute())
            _LOGGER.info("Effective history path: %s", effective_history)
        else:
            state_path = artifacts_path = history_path = None
            _LOGGER.info(
                "Effective configuration path: %s; demo persistence uses isolated temporary storage",
                config_absolute,
            )

        if not config_absolute.exists():
            print(
                f"refrain: configuration file does not exist: {config_absolute}\n"
                "Initialize the standard per-user configuration with `python -m refrain --initialize`, "
                "or provide an existing file with --config.",
                file=sys.stderr,
            )
            return 1

        if arguments.once:
            result = run_startup(
                config_path,
                state_path,
                artifacts_path,
                history_path=history_path,
                history_segment_size=arguments.history_segment_size,
                history_max_segments=arguments.history_max_segments,
                keep_open=_hold_open,
            )
        else:
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
                        history_segment_size=arguments.history_segment_size,
                        history_max_segments=arguments.history_max_segments,
                    )
                else:
                    run_application(
                        config_path,
                        state_path,
                        artifacts_path,
                        shutdown_event=shutdown,
                        history_path=history_path,
                        history_segment_size=arguments.history_segment_size,
                        history_max_segments=arguments.history_max_segments,
                    )
            finally:
                for termination_signal, handler in previous_handlers.items():
                    signal.signal(termination_signal, handler)
            return 0
    except (ApplicationError, ApplicationPathError, InitializationError) as error:
        print(f"refrain: {error}", file=sys.stderr)
        return 1
    snapshot = result.state.snapshot
    action = "Selected" if result.selected_initial_quotation else "Recovered"
    message = f"{action} selection {result.state.revision} for {snapshot.display_date}"
    print(f"{message}; presented stage {result.presented_stage}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

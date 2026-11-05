"""Command-line entry point for continuous and one-shot Refrain operation."""

from __future__ import annotations

import argparse
import logging
import math
import signal
import sys
from collections.abc import Sequence
from threading import Event

from .application import ApplicationError, run_application, run_demo, run_startup

_SERVING_BACKENDS = {"window", "image-server"}


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
    parser.add_argument("--config", required=True, help="application configuration YAML file")
    parser.add_argument("--state", help="persistent state file (required except with --demo; ignored in demo mode)")
    parser.add_argument(
        "--artifacts", help="prepared image directory (required except with --demo; ignored in demo mode)"
    )
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
    arguments = parser.parse_args(argv)
    if arguments.demo is None:
        missing = [name for name in ("--state", "--artifacts") if getattr(arguments, name[2:]) is None]
        if missing:
            parser.error(f"the following arguments are required: {', '.join(missing)}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if arguments.once:
            result = run_startup(
                arguments.config,
                arguments.state,
                arguments.artifacts,
                history_path=arguments.history,
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
                        arguments.config,
                        arguments.demo,
                        shutdown_event=shutdown,
                        history_segment_size=arguments.history_segment_size,
                        history_max_segments=arguments.history_max_segments,
                    )
                else:
                    run_application(
                        arguments.config,
                        arguments.state,
                        arguments.artifacts,
                        shutdown_event=shutdown,
                        history_path=arguments.history,
                        history_segment_size=arguments.history_segment_size,
                        history_max_segments=arguments.history_max_segments,
                    )
            finally:
                for termination_signal, handler in previous_handlers.items():
                    signal.signal(termination_signal, handler)
            return 0
    except ApplicationError as error:
        print(f"refrain: {error}", file=sys.stderr)
        return 1
    snapshot = result.state.snapshot
    action = "Selected" if result.selected_initial_quotation else "Recovered"
    message = f"{action} selection {result.state.revision} for {snapshot.display_date}"
    print(f"{message}; presented stage {result.presented_stage}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

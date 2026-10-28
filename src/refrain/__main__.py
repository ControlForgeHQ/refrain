"""Command-line entry point for continuous and one-shot Refrain operation."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Sequence
from threading import Event

from .application import ApplicationError, run_application, run_startup

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="refrain", description="Run Refrain continuously until interrupted.")
    parser.add_argument("--config", required=True, help="application configuration YAML file")
    parser.add_argument("--state", required=True, help="persistent state file (created if absent)")
    parser.add_argument("--artifacts", required=True, help="directory for prepared image artifacts")
    parser.add_argument("--once", action="store_true", help="run one startup/presentation cycle without scheduling")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if arguments.once:
            result = run_startup(arguments.config, arguments.state, arguments.artifacts, keep_open=_hold_open)
        else:
            shutdown = Event()
            previous_handlers = {}
            try:
                for termination_signal in (signal.SIGINT, signal.SIGTERM):
                    previous_handlers[termination_signal] = signal.signal(
                        termination_signal, lambda signum, frame: shutdown.set()
                    )
                run_application(arguments.config, arguments.state, arguments.artifacts, shutdown_event=shutdown)
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

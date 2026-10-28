"""Command-line entry point for one Refrain startup and presentation cycle."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from threading import Event

from .application import ApplicationError, run_startup

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
    parser = argparse.ArgumentParser(prog="refrain", description="Run one Refrain startup and presentation cycle.")
    parser.add_argument("--config", required=True, help="application configuration YAML file")
    parser.add_argument("--state", required=True, help="persistent state file (created if absent)")
    parser.add_argument("--artifacts", required=True, help="directory for prepared image artifacts")
    arguments = parser.parse_args(argv)
    try:
        result = run_startup(arguments.config, arguments.state, arguments.artifacts, keep_open=_hold_open)
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

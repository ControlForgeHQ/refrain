"""Command-line entry point for continuous and one-shot Refrain operation."""

from __future__ import annotations

import argparse
import logging
import math
import re
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import Event

from .application import ApplicationError, run_application, run_demo, run_show_entry, run_startup, run_test_qr
from .decoration_diagnostic import run_decoration_diagnostic
from .installation import (
    InitializationError,
    InstallationOperationError,
    confirm_operation,
    initialize_installation,
    purge_installation,
    reset_installation,
)
from .paths import ApplicationPathError, resolve_application_paths
from .qr_diagnostic import QRCalibrationError, QRCalibrationParameters, validate_qr_calibration_parameters

_SERVING_BACKENDS = {"window", "image-server"}
_LOGGER = logging.getLogger(__name__)
_ENTRY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def _entry_id(value: str) -> str:
    if not _ENTRY_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "entry ID must be nonempty, start with an ASCII letter or digit, and contain only "
            "ASCII letters, digits, hyphens, and underscores"
        )
    return value


def _qr_version(value: str) -> str | int:
    if value == "auto":
        return value
    if not re.fullmatch(r"[+-]?[0-9]+", value):
        raise argparse.ArgumentTypeError("QR version must be 'auto' or an integer from 1 through 40") from None
    try:
        version = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("QR version must be 'auto' or an integer from 1 through 40") from None
    if not 1 <= version <= 40:
        raise argparse.ArgumentTypeError("QR version must be 'auto' or an integer from 1 through 40")
    return version


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
    parser = argparse.ArgumentParser(
        prog="refrain",
        description="Present Refrain quotations and manage its installation.",
    )
    parser.add_argument("--config", help="application configuration YAML file")
    parser.add_argument("--state", help="persistent state file (ignored in demo and diagnostic modes)")
    parser.add_argument("--artifacts", help="prepared image directory (ignored in demo and diagnostic modes)")
    parser.add_argument(
        "--debug-layout",
        action="store_true",
        help="outline the effective literary presentation region on published images",
    )
    parser.add_argument(
        "--history",
        help=(
            "JSONL global-history file (default: global-history.jsonl beside state; "
            "ignored in demo and diagnostic modes)"
        ),
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
        help="create missing standard installation resources without replacing existing data, then exit",
    )
    modes.add_argument(
        "--reset", action="store_true", help="remove standard runtime state and generated cache, then exit"
    )
    modes.add_argument(
        "--purge", action="store_true", help="remove the complete standard per-user installation, then exit"
    )
    modes.add_argument(
        "--show-entry",
        type=_entry_id,
        metavar="ENTRY_ID",
        help="render and publish one content entry without changing operational state",
    )
    modes.add_argument(
        "--test-qr", action="store_true", help="publish a QR calibration image without changing daily state"
    )
    modes.add_argument(
        "--test-decoration",
        metavar="ID|all",
        help="preview one decoration or all decorations without changing daily state",
    )
    parser.add_argument(
        "--test-output",
        metavar="PATH",
        help="save a full-working-canvas diagnostic PNG instead of opening the preview (requires one decoration ID)",
    )
    parser.add_argument(
        "--test-variants",
        metavar="DIRECTORY",
        help="export all supported diagnostic variants under a new decoration-named subdirectory",
    )
    parser.add_argument(
        "--test-aspect",
        choices=("4:3", "5:3", "16:9", "16:10"),
        help="decoration-preview aspect ratio",
    )
    parser.add_argument(
        "--test-resolution",
        nargs=2,
        type=int,
        metavar=("WIDTH", "HEIGHT"),
        help="requested output dimensions for headless --test-output export",
    )
    parser.add_argument(
        "--test-quotation",
        choices=("short", "medium", "long"),
        help="initial decoration-preview quotation length (default: short)",
    )
    parser.add_argument(
        "--no-qr", action="store_true", help="initially disable QR generation in the decoration preview"
    )
    parser.add_argument(
        "--no-background", action="store_true", help="initially use a white background in the decoration preview"
    )
    parser.add_argument("--no-tinting", action="store_true", help="initially force tintable decoration layers to black")
    parser.add_argument("--qr-payload", help="text or URL encoded into the QR code (default: https://example.com/)")
    parser.add_argument(
        "--qr-version",
        type=_qr_version,
        help="QR version: auto or a fixed version from 1 through 40 (default: auto)",
    )
    parser.add_argument(
        "--qr-error-correction",
        choices=("L", "M", "Q", "H"),
        help="QR error-correction level (default: M)",
    )
    parser.add_argument("--qr-module-size", type=int, help="QR module size in pixels (default: 4)")
    parser.add_argument("--qr-quiet-zone", type=int, help="quiet-zone width in modules (default: 4)")
    parser.add_argument("--qr-right-offset", type=int, help="right edge offset in pixels (default: 40)")
    parser.add_argument("--qr-bottom-offset", type=int, help="bottom edge offset in pixels (default: 40)")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    qr_options = (
        ("--qr-payload", arguments.qr_payload),
        ("--qr-version", arguments.qr_version),
        ("--qr-error-correction", arguments.qr_error_correction),
        ("--qr-module-size", arguments.qr_module_size),
        ("--qr-quiet-zone", arguments.qr_quiet_zone),
        ("--qr-right-offset", arguments.qr_right_offset),
        ("--qr-bottom-offset", arguments.qr_bottom_offset),
    )
    specified_qr_options = [option for option, value in qr_options if value is not None]
    if not arguments.test_qr and specified_qr_options:
        parser.error("QR-specific options are only available with --test-qr: " + ", ".join(specified_qr_options))
    specified_decoration_options = [
        option
        for option, value in (
            ("--test-aspect", arguments.test_aspect),
            ("--test-resolution", arguments.test_resolution),
            ("--test-quotation", arguments.test_quotation),
            ("--no-qr", arguments.no_qr),
            ("--no-background", arguments.no_background),
            ("--no-tinting", arguments.no_tinting),
            ("--test-output", arguments.test_output),
            ("--test-variants", arguments.test_variants),
        )
        if value is not None and value is not False
    ]
    if arguments.test_decoration is None and specified_decoration_options:
        parser.error(
            "decoration-preview options are only available with --test-decoration: "
            + ", ".join(specified_decoration_options)
        )
    if arguments.test_output is not None and arguments.test_decoration is None:
        parser.error("--test-output is only available with --test-decoration")
    if arguments.test_output is not None and arguments.test_aspect is None:
        parser.error("--test-output requires an explicit --test-aspect")
    if arguments.test_resolution is not None and arguments.test_output is None:
        parser.error("--test-resolution is only available with --test-output")
    if arguments.test_output is not None and arguments.test_decoration == "all":
        parser.error("--test-output requires exactly one decoration ID; 'all' cannot be exported")
    if arguments.test_output is not None and arguments.test_variants is not None:
        parser.error("--test-output and --test-variants are mutually exclusive")
    if arguments.test_variants is not None and arguments.test_decoration == "all":
        parser.error("--test-variants requires one specific decoration ID; 'all' is not supported")
    if arguments.test_variants is not None:
        incompatible_variants = [
            option
            for option, selected in (
                ("--test-aspect", arguments.test_aspect is not None),
                ("--test-quotation", arguments.test_quotation is not None),
                ("--no-qr", arguments.no_qr),
            )
            if selected
        ]
        if incompatible_variants:
            parser.error(
                "--test-variants generates all aspect ratios, quotation lengths, and effective QR states; "
                "do not combine it with " + ", ".join(incompatible_variants)
            )
    conflicting_modes = [
        option
        for option, selected in (
            ("--once", arguments.once),
            ("--demo", arguments.demo is not None),
            ("--initialize", arguments.initialize),
            ("--reset", arguments.reset),
            ("--purge", arguments.purge),
            ("--show-entry", arguments.show_entry is not None),
            ("--test-qr", arguments.test_qr),
        )
        if selected
    ]
    if arguments.test_decoration is not None and conflicting_modes:
        parser.error("--test-decoration cannot be combined with other modes: " + ", ".join(conflicting_modes))
    default_qr_parameters = QRCalibrationParameters()
    qr_parameters = QRCalibrationParameters(
        payload=arguments.qr_payload if arguments.qr_payload is not None else default_qr_parameters.payload,
        error_correction=(
            arguments.qr_error_correction
            if arguments.qr_error_correction is not None
            else default_qr_parameters.error_correction
        ),
        version=None if arguments.qr_version in (None, "auto") else arguments.qr_version,
        module_size=(
            arguments.qr_module_size if arguments.qr_module_size is not None else default_qr_parameters.module_size
        ),
        quiet_zone=(
            arguments.qr_quiet_zone if arguments.qr_quiet_zone is not None else default_qr_parameters.quiet_zone
        ),
        right_offset=(
            arguments.qr_right_offset if arguments.qr_right_offset is not None else default_qr_parameters.right_offset
        ),
        bottom_offset=(
            arguments.qr_bottom_offset
            if arguments.qr_bottom_offset is not None
            else default_qr_parameters.bottom_offset
        ),
    )
    if arguments.test_qr:
        try:
            validate_qr_calibration_parameters(qr_parameters)
        except QRCalibrationError as error:
            parser.error(str(error))
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

        if arguments.reset or arguments.purge:
            overrides = [
                f"--{name}"
                for name in ("config", "state", "artifacts", "history")
                if getattr(arguments, name) is not None
            ]
            operation = "--reset" if arguments.reset else "--purge"
            if overrides:
                parser.error(f"{operation} cannot be combined with path overrides: " + ", ".join(overrides))
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
                removed = purge_installation(paths)
                for path in removed:
                    print(f"Removed: {path}")
                print("Purge complete.")
            return 0

        paths = resolve_application_paths()
        config_path = arguments.config if arguments.config is not None else paths.config_file
        config_absolute = Path(config_path).absolute()
        if (
            arguments.demo is None
            and arguments.show_entry is None
            and not arguments.test_qr
            and arguments.test_decoration is None
        ):
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
                "Effective configuration path: %s; %s",
                config_absolute,
                (
                    "diagnostic presentation does not use production persistence"
                    if arguments.show_entry is not None or arguments.test_qr or arguments.test_decoration is not None
                    else "demo persistence uses isolated temporary storage"
                ),
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
                debug_layout=arguments.debug_layout,
                history_path=history_path,
                history_segment_size=arguments.history_segment_size,
                history_max_segments=arguments.history_max_segments,
                keep_open=_hold_open,
            )
        elif arguments.show_entry is not None:
            run_show_entry(config_path, arguments.show_entry, debug_layout=arguments.debug_layout)
            return 0
        elif arguments.test_qr:
            output, _ = run_test_qr(config_path, qr_parameters)
            print(f"QR diagnostic image saved to {output}")
            return 0
        elif arguments.test_decoration is not None:
            run_decoration_diagnostic(
                config_path,
                selection=arguments.test_decoration,
                aspect_ratio=arguments.test_aspect,
                requested_output_size=(
                    None if arguments.test_resolution is None else tuple(arguments.test_resolution)
                ),
                quotation=arguments.test_quotation or "short",
                qr_enabled=False if arguments.no_qr else None,
                background_enabled=not arguments.no_background,
                tinting_enabled=not arguments.no_tinting,
                debug_layout=arguments.debug_layout,
                output_path=arguments.test_output,
                variants_directory=arguments.test_variants,
            )
            return 0
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
                        debug_layout=arguments.debug_layout,
                        shutdown_event=shutdown,
                        history_segment_size=arguments.history_segment_size,
                        history_max_segments=arguments.history_max_segments,
                    )
                else:
                    run_application(
                        config_path,
                        state_path,
                        artifacts_path,
                        debug_layout=arguments.debug_layout,
                        shutdown_event=shutdown,
                        history_path=history_path,
                        history_segment_size=arguments.history_segment_size,
                        history_max_segments=arguments.history_max_segments,
                    )
            finally:
                for termination_signal, handler in previous_handlers.items():
                    signal.signal(termination_signal, handler)
            return 0
    except (ApplicationError, ApplicationPathError, InitializationError, InstallationOperationError) as error:
        print(f"refrain: {error}", file=sys.stderr)
        return 1
    snapshot = result.state.snapshot
    action = "Selected" if result.selected_initial_quotation else "Recovered"
    message = f"{action} selection {result.state.revision} for {snapshot.display_date}"
    print(f"{message}; presented stage {result.presented_stage}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

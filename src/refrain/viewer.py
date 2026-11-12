"""One-shot presentation inspection and PNG export."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageOps

from .config import ApplicationConfiguration, ApplicationConfigurationError, load_application_config
from .content import ContentEntry, ContentLibraryError, Quotation, load_content_library, normalize_quotation
from .display.coordinator import PublicationResult, PublicationStatus
from .geometry import (
    SUPPORTED_PRESENTATION_ASPECTS,
    ResolvedOutputSpecification,
    design_canvas_for_aspect,
)
from .paths import ApplicationPathError, resolve_application_paths
from .preparation import (
    DailyImagePreparationError,
    PresentationOverrides,
    prepare_daily_images,
)
from .presentation import build_presentation_snapshot
from .presentation_diagnostics import overlay_presentation_diagnostics
from .runtime_control import (
    RuntimeAuthenticationError,
    RuntimeControlClient,
    RuntimeControlError,
    RuntimeProtocolError,
    RuntimeUnavailable,
    RuntimeUnconfirmed,
    RuntimeUnsupportedProtocol,
)
from .scheduling import resolve_reveal_stages

_ENTRY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")

_PREVIEW_ENTRY = ContentEntry(
    id="@preview",
    quotations=tuple(
        Quotation(text, normalize_quotation(text))
        for text in (
            "A quiet moment can change the shape of a day.",
            (
                "The light finds its way through the smallest opening, and turns an ordinary room "
                "into a place of possibility."
            ),
            (
                "A thought may begin as a small and private spark, yet grow brighter when we give it "
                "room to breathe. Words travel farther than we expect, carrying a little patience, "
                "wonder, and courage into the lives they touch."
            ),
        )
    ),
    source="A Field Note",
    attribution="Refrain Preview",
)
_DEFAULT_SELECTOR = ("@preview", 2)


class ViewerError(Exception):
    """Raised when a requested preview cannot be rendered or presented."""


def parse_entry_selector(value: str) -> tuple[str, int]:
    """Parse an exact entry ID and optional positive, one-based quotation number."""
    if value == "@preview":
        return value, 1
    if value.count(":") > 1:
        raise argparse.ArgumentTypeError("entry selector must be ENTRY_ID or ENTRY_ID:QUOTATION_NUMBER")
    entry_id, separator, quotation_number = value.partition(":")
    if entry_id != "@preview" and not _ENTRY_ID.fullmatch(entry_id):
        raise argparse.ArgumentTypeError("entry ID must contain only ASCII letters, digits, hyphens, and underscores")
    if not separator:
        return entry_id, 1
    if not quotation_number.isascii() or not quotation_number.isdecimal() or int(quotation_number) < 1:
        raise argparse.ArgumentTypeError("quotation number must be a positive 1-based integer")
    return entry_id, int(quotation_number)


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "resource ID must contain only ASCII letters, digits, hyphens, and underscores"
        )
    return value


def _positive_font_size(value: str) -> int:
    if not value.isascii() or not value.isdecimal() or int(value) < 1:
        raise argparse.ArgumentTypeError("font size must be a positive integer number of design-canvas pixels")
    return int(value)


def _select_entry(
    configuration: ApplicationConfiguration,
    selector: tuple[str, int],
) -> tuple[ContentEntry, Quotation]:
    entry_id, quotation_number = selector
    if entry_id == "@preview":
        entry = _PREVIEW_ENTRY
    else:
        try:
            entries = load_content_library(configuration.content_directory)
        except ContentLibraryError as error:
            raise ViewerError(f"content library is invalid: {error}") from error
        entry = next((candidate for candidate in entries if candidate.id == entry_id), None)
        if entry is None:
            raise ViewerError(
                f"content entry {entry_id!r} was not found in configured content library "
                f"{configuration.content_directory}; confirm that the ID is exact and the entry has "
                "at least one usable quotation"
            )
    if quotation_number > len(entry.quotations):
        raise ViewerError(
            f"quotation number {quotation_number} is out of range for entry {entry_id!r}; "
            f"the entry has {len(entry.quotations)} usable quotation(s)"
        )
    return entry, entry.quotations[quotation_number - 1]


def _output_specification(aspect: str, resolution: tuple[int, int] | None) -> ResolvedOutputSpecification:
    if aspect not in SUPPORTED_PRESENTATION_ASPECTS:
        raise ViewerError(f"unsupported output aspect: {aspect!r}")
    dimensions = design_canvas_for_aspect(aspect)[0] if resolution is None else resolution
    try:
        return ResolvedOutputSpecification(aspect, dimensions)
    except ValueError as error:
        raise ViewerError(f"invalid output resolution: {error}") from error


def render_preview(
    configuration: ApplicationConfiguration,
    selector: tuple[str, int] = _DEFAULT_SELECTOR,
    output_specification: ResolvedOutputSpecification | None = None,
    *,
    overrides: PresentationOverrides | None = None,
    debug_layout: bool = False,
) -> Image.Image:
    """Render one fully revealed output image without runtime persistence or backends."""
    specification = output_specification or _output_specification("16:10", None)
    return render_preview_variants(
        configuration,
        selector,
        (specification,),
        overrides=overrides,
        debug_layout=debug_layout,
    )[specification]


def render_preview_variants(
    configuration: ApplicationConfiguration,
    selector: tuple[str, int],
    output_specifications: Sequence[ResolvedOutputSpecification],
    *,
    overrides: PresentationOverrides | None = None,
    debug_layout: bool = False,
) -> Mapping[ResolvedOutputSpecification, Image.Image]:
    """Render one coherent, fully revealed presentation across output specifications."""
    entry, quotation = _select_entry(configuration, selector)
    try:
        snapshot = build_presentation_snapshot(configuration, entry, quotation, date.today())
        stages = resolve_reveal_stages(snapshot)

        def annotate_diagnostics(_specification, image, diagnostics) -> None:
            annotated = overlay_presentation_diagnostics(image, diagnostics)
            if annotated is not image:
                image.paste(annotated)
                annotated.close()

        prepared = prepare_daily_images(
            snapshot,
            (stages[-1],),
            configuration,
            output_specifications,
            overrides=overrides,
            on_presentation_image=annotate_diagnostics if debug_layout else None,
        )
    except (ValueError, TypeError) as error:
        raise ViewerError(f"cannot prepare preview for entry {entry.id!r}: {error}") from error
    try:
        return {specification: images[0] for specification, images in prepared.items()}
    except Exception:
        for images in prepared.values():
            for image in images:
                image.close()
        raise


def show_preview_window(image: Image.Image) -> None:
    """Display an already-rendered output image, scaling only a private desktop copy."""
    try:
        import tkinter as tk

        from PIL import ImageTk
    except (ImportError, RuntimeError) as error:
        raise ViewerError(f"window display is unavailable because Tk support is missing: {error}") from error

    root = None
    desktop_image = None
    try:
        root = tk.Tk()
        root.title("Refrain Viewer")
        max_size = (max(1, root.winfo_screenwidth() - 80), max(1, root.winfo_screenheight() - 120))
        desktop_image = _fit_preview_image(image, max_size)
        photo = ImageTk.PhotoImage(desktop_image, master=root)
        label = tk.Label(root, image=photo)
        label.image = photo
        label.pack()
        root.mainloop()
    except tk.TclError as error:
        raise ViewerError(f"window display is unavailable; start a graphical desktop session: {error}") from error
    finally:
        if desktop_image is not None:
            desktop_image.close()
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass


def _fit_preview_image(image: Image.Image, available_size: tuple[int, int]) -> Image.Image:
    """Return a proportionally scaled desktop copy without changing the output image."""
    return ImageOps.contain(image.copy(), available_size, method=Image.Resampling.LANCZOS)


def run_viewer(
    *,
    config_file: str | Path | None = None,
    selector: tuple[str, int] = _DEFAULT_SELECTOR,
    aspect: str = "16:10",
    resolution: tuple[int, int] | None = None,
    output: str | Path | None = None,
    window: bool = False,
    overrides: PresentationOverrides | None = None,
    debug_layout: bool = False,
) -> None:
    """Load one configuration and render/export a single presentation."""
    if config_file is None:
        try:
            config_file = resolve_application_paths().config_file
        except ApplicationPathError as error:
            raise ViewerError(str(error)) from error
    config_path = Path(config_file).absolute()
    if not config_path.is_file():
        raise ViewerError(
            f"configuration file does not exist: {config_path}; initialize Refrain or provide an existing file with "
            "--config"
        )
    try:
        configuration = load_application_config(config_path)
    except ApplicationConfigurationError as error:
        raise ViewerError(f"application configuration is invalid: {error}") from error

    specification = _output_specification(aspect, resolution)
    image = render_preview(
        configuration,
        selector,
        specification,
        overrides=PresentationOverrides() if overrides is None else overrides,
        debug_layout=debug_layout,
    )
    try:
        if output is not None:
            try:
                image.save(output, format="PNG")
            except OSError as error:
                raise ViewerError(f"cannot write PNG output {str(output)!r}: {error}") from error
        if window or output is None:
            show_preview_window(image)
    finally:
        image.close()


def _run_destination_discovery() -> int:
    try:
        paths = resolve_application_paths()
        destinations = RuntimeControlClient(Path(paths.control_metadata_file)).discover()
    except RuntimeUnavailable as error:
        print(f"refrain-viewer: {error}", file=sys.stderr)
        return 1
    except RuntimeAuthenticationError as error:
        print(
            f"refrain-viewer: {error}; restart the resident Refrain runtime for this user and try again.",
            file=sys.stderr,
        )
        return 1
    except RuntimeUnsupportedProtocol as error:
        print(
            f"refrain-viewer: {error}; ensure the client and resident runtime versions are compatible.",
            file=sys.stderr,
        )
        return 1
    except RuntimeProtocolError as error:
        print(
            f"refrain-viewer: runtime-control protocol error: {error}; restart the resident Refrain runtime.",
            file=sys.stderr,
        )
        return 1
    except (ApplicationPathError, RuntimeControlError) as error:
        print(f"refrain-viewer: runtime destination discovery failed: {error}", file=sys.stderr)
        return 1

    if not destinations:
        print("No destinations are configured in the resident Refrain runtime.")
        return 0

    headers = ("Destination", "Aspect", "Resolution", "Transient", "Participation", "Availability", "Withdrawn")
    rows = []
    for destination in destinations:
        specification = destination["output_specification"]
        width, height = specification.requested_output_size
        rows.append(
            (
                destination["identifier"],
                specification.aspect_ratio,
                f"{width}x{height}",
                "yes" if destination["supports_transient"] else "no",
                "participating" if destination["participating"] else "not participating",
                "available" if destination["available"] else "unavailable/failed",
                "yes" if destination["withdrawn"] else "no",
            )
        )
    table = (headers, *rows)
    widths = tuple(max(len(row[index]) for row in table) for index in range(len(headers)))
    print("\n".join("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in table))
    return 0


def _select_push_destinations(
    destinations: Sequence[dict[str, object]],
    target: str,
) -> tuple[str, tuple[dict[str, object], ...], dict[str, ResolvedOutputSpecification]]:
    if target == "all":
        selected = tuple(
            destination for destination in destinations if destination["participating"] and not destination["withdrawn"]
        )
        if not selected:
            raise ViewerError(
                "no resident destinations remain participating in publication; restart Refrain with at least one "
                "configured participating destination"
            )
    else:
        destination = next((record for record in destinations if record["identifier"] == target), None)
        if destination is None:
            raise ViewerError(f"destination {target!r} is unknown to the resident Refrain runtime")
        if destination["withdrawn"]:
            raise ViewerError(f"destination {target!r} is intentionally withdrawn and cannot receive a push")
        if not destination["participating"]:
            raise ViewerError(f"destination {target!r} is not participating in publication")
        selected = (destination,)

    unsupported = [str(destination["identifier"]) for destination in selected if not destination["supports_transient"]]
    if unsupported:
        raise ViewerError(
            "transient publication is unsupported by "
            + ", ".join(repr(identifier) for identifier in unsupported)
            + "; configure a transient-capable destination or select a supported target"
        )

    specifications = {str(destination["identifier"]): destination["output_specification"] for destination in selected}
    return target, selected, specifications


def _report_push_result(
    result: PublicationResult,
    destinations: Sequence[dict[str, object]],
) -> int:
    expected = {str(destination["identifier"]) for destination in destinations}
    if (
        result.status is PublicationStatus.SUCCEEDED
        and set(result.destinations) == expected
        and all(success is True for success, _error in result.destinations.values())
    ):
        print("Push completed successfully.")
        return 0

    messages = {
        PublicationStatus.BUSY: (
            "push was not accepted because publication is busy; wait for the current update to finish"
        ),
        PublicationStatus.FAILED: "push publication failed",
        PublicationStatus.STOPPING: "the resident Refrain runtime is stopping or rejected the push",
        PublicationStatus.INVALID: (
            "the resident Refrain runtime rejected the push as invalid; a destination or output specification may "
            "have changed since discovery"
        ),
        PublicationStatus.UNSUPPORTED: "the resident Refrain runtime does not support transient publication",
        PublicationStatus.WITHDRAWN: "a selected destination is intentionally withdrawn",
        PublicationStatus.DESTINATION_NOT_FOUND: "a selected destination is no longer configured",
    }
    if result.status is PublicationStatus.SUCCEEDED:
        message = "the runtime did not report successful completion for every selected destination"
    else:
        message = messages.get(result.status, f"push ended with unexpected status {result.status.value!r}")
    print(f"refrain-viewer: {message}.", file=sys.stderr)
    for identifier in sorted(expected | set(result.destinations)):
        if identifier not in result.destinations:
            print(f"  {identifier}: no terminal outcome reported", file=sys.stderr)
            continue
        success, error = result.destinations[identifier]
        if success is not True:
            detail = error or ("publication failed" if success is False else "no terminal outcome reported")
            print(f"  {identifier}: {detail}", file=sys.stderr)
    return 1


def _run_push(
    target: str,
    *,
    config_file: str | Path | None,
    selector: tuple[str, int],
    overrides: PresentationOverrides,
    debug_layout: bool,
) -> int:
    try:
        paths = resolve_application_paths()
        client = RuntimeControlClient(Path(paths.control_metadata_file))
        destinations = client.discover()
        runtime_target, selected, specifications = _select_push_destinations(destinations, target)
    except RuntimeUnavailable as error:
        print(f"refrain-viewer: {error}", file=sys.stderr)
        return 1
    except RuntimeAuthenticationError as error:
        print(
            f"refrain-viewer: {error}; restart the resident Refrain runtime for this user and try again.",
            file=sys.stderr,
        )
        return 1
    except RuntimeUnsupportedProtocol as error:
        print(
            f"refrain-viewer: {error}; ensure the client and resident runtime versions are compatible.",
            file=sys.stderr,
        )
        return 1
    except RuntimeProtocolError as error:
        print(
            f"refrain-viewer: runtime-control protocol error: {error}; restart the resident Refrain runtime.",
            file=sys.stderr,
        )
        return 1
    except (ApplicationPathError, RuntimeControlError, ViewerError) as error:
        print(f"refrain-viewer: push destination discovery failed: {error}", file=sys.stderr)
        return 1

    config_path = Path(config_file if config_file is not None else paths.config_file).absolute()
    if not config_path.is_file():
        print(
            f"refrain-viewer: configuration file does not exist: {config_path}; initialize Refrain or provide an "
            "existing file with --config",
            file=sys.stderr,
        )
        return 1
    try:
        configuration = load_application_config(config_path)
    except ApplicationConfigurationError as error:
        print(f"refrain-viewer: application configuration is invalid: {error}", file=sys.stderr)
        return 1

    print("Preparing presentation variants for push.", flush=True)
    try:
        images = render_preview_variants(
            configuration,
            selector,
            tuple(dict.fromkeys(specifications.values())),
            overrides=overrides,
            debug_layout=debug_layout,
        )
    except (ViewerError, DailyImagePreparationError) as error:
        print(f"refrain-viewer: {error}", file=sys.stderr)
        return 1

    def report_accepted() -> None:
        print("Push accepted; publication has begun.", flush=True)

    try:
        result = client.publish_transient(
            runtime_target,
            specifications,
            images,
            on_accepted=report_accepted,
        )
    except RuntimeUnconfirmed:
        print(
            "refrain-viewer: push outcome is unconfirmed; publication may have occurred. Do not retry automatically.",
            file=sys.stderr,
        )
        return 1
    except RuntimeUnavailable as error:
        print(f"refrain-viewer: {error}", file=sys.stderr)
        return 1
    except RuntimeAuthenticationError as error:
        print(
            f"refrain-viewer: {error}; restart the resident Refrain runtime for this user and try again.",
            file=sys.stderr,
        )
        return 1
    except RuntimeUnsupportedProtocol as error:
        print(
            f"refrain-viewer: {error}; ensure the client and resident runtime versions are compatible.",
            file=sys.stderr,
        )
        return 1
    except RuntimeProtocolError as error:
        print(
            f"refrain-viewer: runtime-control request failed: {error}; verify the requested destinations and "
            "configured image limits, then restart the resident Refrain runtime if the error persists.",
            file=sys.stderr,
        )
        return 1
    except RuntimeControlError as error:
        print(f"refrain-viewer: runtime-control push failed: {error}", file=sys.stderr)
        return 1
    finally:
        for image in images.values():
            image.close()
    return _report_push_result(result, selected)


def _validate_discovery_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> None:
    conflicts = []
    for option, value in (
        ("--config", arguments.config),
        ("--entry", arguments.entry),
        ("--font", arguments.font),
        ("--quotation-face", arguments.quotation_face),
        ("--source-face", arguments.source_face),
        ("--attribution-face", arguments.attribution_face),
        ("--min-font-size", arguments.min_font_size),
        ("--max-font-size", arguments.max_font_size),
        ("--background", arguments.background),
        ("--decoration", arguments.decoration),
        ("--text-color", arguments.text_color),
        ("--tint", arguments.tint),
        ("--style", arguments.style),
        ("--qr/--no-qr", arguments.qr_enabled is not None),
        ("--aspect", arguments.aspect),
        ("--resolution", arguments.resolution),
        ("--output", arguments.output),
        ("--window", arguments.window),
        ("--debug-layout", arguments.debug_layout),
        ("--push", arguments.push),
    ):
        if value is not None and value is not False:
            conflicts.append(option)
    if conflicts:
        parser.error("--list-destinations is standalone and cannot be combined with " + ", ".join(conflicts))


def _validate_push_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> None:
    conflicts = []
    for option, value in (
        ("--window", arguments.window),
        ("--output", arguments.output),
        ("--aspect", arguments.aspect),
        ("--resolution", arguments.resolution),
        ("--list-destinations", arguments.list_destinations),
    ):
        if value is not None and value is not False:
            conflicts.append(option)
    if conflicts:
        parser.error("--push is mutually exclusive with " + ", ".join(conflicts))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refrain-viewer",
        description="Render one Refrain presentation for local inspection or PNG export.",
    )
    parser.add_argument("--config", help="application configuration YAML file")
    parser.add_argument("--entry", type=parse_entry_selector, metavar="ENTRY_ID[:N]")
    parser.add_argument("--font", type=_identifier, metavar="FONT_ID")
    parser.add_argument("--quotation-face", type=_identifier, metavar="FACE_ID")
    parser.add_argument("--source-face", type=_identifier, metavar="FACE_ID")
    parser.add_argument("--attribution-face", type=_identifier, metavar="FACE_ID")
    parser.add_argument(
        "--min-font-size",
        type=_positive_font_size,
        metavar="PIXELS",
        help="minimum design-canvas pixel size for automatic quotation fitting",
    )
    parser.add_argument(
        "--max-font-size",
        type=_positive_font_size,
        metavar="PIXELS",
        help="maximum design-canvas pixel size for automatic quotation fitting",
    )
    parser.add_argument("--background", type=_identifier, metavar="BACKGROUND_ID|none")
    parser.add_argument("--decoration", type=_identifier, metavar="DECORATION_ID|none")
    parser.add_argument("--text-color", type=_identifier, metavar="COLOR_ID")
    parser.add_argument("--tint", type=_identifier, metavar="COLOR_ID")
    parser.add_argument("--style", choices=("centered", "left-aligned"))
    qr_options = parser.add_mutually_exclusive_group()
    qr_options.add_argument("--qr", dest="qr_enabled", action="store_true")
    qr_options.add_argument("--no-qr", dest="qr_enabled", action="store_false")
    parser.set_defaults(qr_enabled=None)
    parser.add_argument("--aspect", choices=tuple(SUPPORTED_PRESENTATION_ASPECTS))
    parser.add_argument("--resolution", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--output", type=Path, metavar="PATH")
    parser.add_argument("--window", action="store_true", help="also open a simple display-only viewer window")
    parser.add_argument("--debug-layout", action="store_true", help="show presentation geometry diagnostics")
    parser.add_argument(
        "--list-destinations",
        action="store_true",
        help="list destinations exposed by the running Refrain runtime and exit",
    )
    parser.add_argument(
        "--push",
        metavar="TARGET",
        help="publish a rendered presentation through resident destinations",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.list_destinations:
        _validate_discovery_arguments(parser, arguments)
        return _run_destination_discovery()
    if arguments.push is not None:
        _validate_push_arguments(parser, arguments)

    overrides = PresentationOverrides(
        font=arguments.font,
        font_faces={
            role: face
            for role, face in (
                ("quotation", arguments.quotation_face),
                ("source", arguments.source_face),
                ("attribution", arguments.attribution_face),
            )
            if face is not None
        },
        min_font_size=arguments.min_font_size,
        max_font_size=arguments.max_font_size,
        background=arguments.background,
        decoration=arguments.decoration,
        text_color=arguments.text_color,
        tint=arguments.tint,
        style=arguments.style,
        qr_enabled=arguments.qr_enabled,
    )
    resolution = None if arguments.resolution is None else tuple(arguments.resolution)
    if arguments.push is not None:
        return _run_push(
            arguments.push,
            config_file=arguments.config,
            selector=arguments.entry or _DEFAULT_SELECTOR,
            overrides=overrides,
            debug_layout=arguments.debug_layout,
        )
    try:
        run_viewer(
            config_file=arguments.config,
            selector=arguments.entry or _DEFAULT_SELECTOR,
            aspect=arguments.aspect or "16:10",
            resolution=resolution,
            output=arguments.output,
            window=arguments.window,
            overrides=overrides,
            debug_layout=arguments.debug_layout,
        )
    except (ApplicationPathError, ViewerError, DailyImagePreparationError) as error:
        print(f"refrain-viewer: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "ViewerError",
    "main",
    "parse_entry_selector",
    "render_preview",
    "run_viewer",
    "show_preview_window",
]

"""One-shot presentation inspection and PNG export."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps

from .config import ApplicationConfiguration, ApplicationConfigurationError, load_application_config
from .content import ContentEntry, ContentLibraryError, Quotation, load_content_library, normalize_quotation
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
    entry, quotation = _select_entry(configuration, selector)
    try:
        snapshot = build_presentation_snapshot(configuration, entry, quotation, date.today())
        specification = output_specification or _output_specification("16:10", None)
        stages = resolve_reveal_stages(snapshot)
        prepared = prepare_daily_images(
            snapshot,
            (stages[-1],),
            configuration,
            (specification,),
            overrides=overrides,
            debug_layout=debug_layout,
        )
    except (ValueError, TypeError) as error:
        raise ViewerError(f"cannot prepare preview for entry {entry.id!r}: {error}") from error
    return prepared[specification][0]


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refrain-viewer",
        description="Render one Refrain presentation for local inspection or PNG export.",
    )
    parser.add_argument("--config", help="application configuration YAML file")
    parser.add_argument("--entry", type=parse_entry_selector, default=_DEFAULT_SELECTOR, metavar="ENTRY_ID[:N]")
    parser.add_argument("--font", type=_identifier, metavar="FONT_ID")
    parser.add_argument("--quotation-face", type=_identifier, metavar="FACE_ID")
    parser.add_argument("--source-face", type=_identifier, metavar="FACE_ID")
    parser.add_argument("--attribution-face", type=_identifier, metavar="FACE_ID")
    parser.add_argument("--background", type=_identifier, metavar="BACKGROUND_ID|none")
    parser.add_argument("--decoration", type=_identifier, metavar="DECORATION_ID|none")
    parser.add_argument("--text-color", type=_identifier, metavar="COLOR_ID")
    parser.add_argument("--tint", type=_identifier, metavar="COLOR_ID")
    parser.add_argument("--style", choices=("centered", "left-aligned"))
    qr_options = parser.add_mutually_exclusive_group()
    qr_options.add_argument("--qr", dest="qr_enabled", action="store_true")
    qr_options.add_argument("--no-qr", dest="qr_enabled", action="store_false")
    parser.set_defaults(qr_enabled=None)
    parser.add_argument("--aspect", choices=tuple(SUPPORTED_PRESENTATION_ASPECTS), default="16:10")
    parser.add_argument("--resolution", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--output", type=Path, metavar="PATH")
    parser.add_argument("--window", action="store_true", help="also open a simple display-only viewer window")
    parser.add_argument("--debug-layout", action="store_true", help="outline the effective literary region")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
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
        background=arguments.background,
        decoration=arguments.decoration,
        text_color=arguments.text_color,
        tint=arguments.tint,
        style=arguments.style,
        qr_enabled=arguments.qr_enabled,
    )
    resolution = None if arguments.resolution is None else tuple(arguments.resolution)
    try:
        run_viewer(
            config_file=arguments.config,
            selector=arguments.entry,
            aspect=arguments.aspect,
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

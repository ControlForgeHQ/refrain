"""Interactive, state-isolated visual inspection of decoration presentations."""

from __future__ import annotations

import colorsys
import hashlib
import math
import os
import queue
import random
import select
import sys
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from importlib.resources import files
from math import gcd
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .application import (
    ApplicationError,
    BackendFactory,
    _build_snapshot,
    _default_backend_factory,
    _load_configuration,
)
from .assets import discover_decorations
from .config import _BUNDLED_DECORATION_IDS, _parse_presentation_insets
from .content import ContentEntry, Quotation, normalize_quotation
from .display.coordinator import DisplayPublicationCoordinator
from .geometry import (
    PixelBounds,
    PresentationGeometryError,
    PresentationInsets,
    resolve_presentation_geometry,
    round_half_up,
)
from .preparation import PreparationDiagnostics, prepare_daily_images
from .qr import QRCodePlacementError, resolve_qr_placement
from .renderer import annotate_literary_region
from .scheduling import resolve_reveal_stages

_QUOTATIONS = (
    ("I am large, I contain multitudes.", "Song of Myself", "Walt Whitman"),
    (
        "I have always imagined that Paradise will be a kind of library.",
        "The Library of Babel",
        "Jorge Luis Borges",
    ),
    (
        "There is no frigate like a book to take us lands away, nor any coursers like a page "
        "of prancing poetry. This traverse may the poorest take without oppress of toll; "
        "how frugal is the chariot that bears the human soul.",
        "A Book",
        "Emily Dickinson",
    ),
)
_QUOTATION_NAMES = ("short", "medium", "long")
_ASPECTS = {"4:3": (4, 3), "16:9": (16, 9), "16:10": (16, 10)}
_QR_COLOR = "#FF00FF"


@contextmanager
def single_key_input():
    """Yield a blocking key reader and restore terminal settings on exit."""
    if not sys.stdin.isatty():
        raise ApplicationError("decoration diagnostic requires an interactive terminal; run it in a terminal")
    if sys.platform == "win32":
        import msvcrt

        def read_windows_key():
            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                return key + msvcrt.getwch()
            return key

        yield read_windows_key
        return
    if os.name == "posix":
        import termios
        import tty

        try:
            fd = sys.stdin.fileno()
            settings = termios.tcgetattr(fd)
        except (OSError, ValueError, termios.error) as error:
            raise ApplicationError(f"cannot access interactive terminal input: {error}") from error
        try:
            tty.setcbreak(fd)

            def read_posix_key():
                key = sys.stdin.read(1)
                if key != "\x1b":
                    return key
                sequence = key
                while len(sequence) < 6 and select.select([sys.stdin], [], [], 0.03)[0]:
                    sequence += sys.stdin.read(1)
                    if sequence[-1] in "~ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
                        break
                return sequence

            yield read_posix_key
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        return
    raise ApplicationError("single-key input is unsupported on this platform; use Linux or Windows")


@dataclass(frozen=True)
class DiagnosticState:
    """Interactive decoration selection and diagnostic-only presentation options."""

    decoration_ids: tuple[str, ...]
    decoration_index: int = 0
    quotation_index: int = 0
    aspect_ratio: str = "configured"
    qr_enabled: bool = True
    background_enabled: bool = True
    tinting_enabled: bool = True
    debug_layout: bool = False
    all_decorations: bool = True
    geometry_overrides: tuple[tuple[str, GeometryOverrides], ...] = ()

    @property
    def decoration(self) -> str | None:
        if not self.decoration_ids:
            return None
        return self.decoration_ids[self.decoration_index]


@dataclass(frozen=True)
class _QRPosition:
    method: str
    offset: int = 20


@dataclass(frozen=True)
class GeometryOverrides:
    """Temporary per-decoration geometry changes for this diagnostic session."""

    presentation_insets: tuple[tuple[str, int], ...] = ()
    qr_horizontal: _QRPosition | None = None
    qr_vertical: _QRPosition | None = None


@dataclass(frozen=True)
class _RenderedPreview:
    image: Image.Image
    snapshot: object
    diagnostics: PreparationDiagnostics
    configuration: object
    state: DiagnosticState
    message: str | None = None


class _StableChoices(random.Random):
    def __init__(self, identity: str) -> None:
        super().__init__(0)
        self.identity = identity

    def choice(self, sequence):
        digest = hashlib.sha256((self.identity + repr(tuple(sequence))).encode("utf-8")).digest()
        return sequence[int.from_bytes(digest, "big") % len(sequence)]


def _discover(configuration):
    problems = []

    def report(field, message, severity=0):
        problems.append((field, message))

    registry = discover_decorations(
        files("refrain").joinpath("assets", "decorations"),
        configuration.file.parent / "assets" / "decorations",
        _BUNDLED_DECORATION_IDS,
        set(configuration.fonts),
        set(configuration.backgrounds),
        report,
        lambda value, field, reporter, severity=0: _parse_presentation_insets(value, field, reporter, severity),
    )
    return registry, problems


def _validated_decoration(configuration, identifier, manifest, initial_warnings=()):
    registry, warnings = _discover(configuration)
    problems = [
        f"{field}: {message}"
        for field, message in warnings
        if (field == str(manifest) or field.startswith(f"{manifest}.") or field.startswith(f"{manifest}["))
        and (field, message) not in initial_warnings
    ]
    resource = registry.get(identifier)
    if problems:
        raise ApplicationError("; ".join(problems))
    if resource is None or resource.manifest != manifest:
        raise ApplicationError(f"decoration {identifier!r} at {manifest} is unavailable or invalid; correct its files")
    return resource


def _with_aspect(configuration, aspect_ratio: str):
    if aspect_ratio == "configured":
        return configuration
    width = configuration.output_size[0]
    aspect_width, aspect_height = _ASPECTS[aspect_ratio]
    divisor = gcd(aspect_width, aspect_height)
    unit_width, unit_height = aspect_width // divisor, aspect_height // divisor
    units = max(1, (2 * width + unit_width) // (2 * unit_width))
    return replace(configuration, output_size=(units * unit_width, units * unit_height))


def _decoration_geometry(configuration, decoration, overrides: GeometryOverrides | None = None):
    """Resolve effective geometry and its source without mutating shared resources."""
    overrides = overrides or GeometryOverrides()
    insets = decoration.presentation_insets or configuration.presentation_insets
    values = {name: getattr(insets, name) for name in ("left", "right", "top", "bottom")}
    values.update(dict(overrides.presentation_insets))

    metadata = dict(decoration.qr_positioning)

    def axis_position(axis: str) -> _QRPosition:
        if axis == "horizontal":
            if metadata.get("qr_centered") == "horizontal":
                return _QRPosition("center")
            for name in ("left", "right"):
                key = f"qr_from_{name}"
                if key in metadata:
                    return _QRPosition(name, metadata[key] if type(metadata[key]) is int else 20)
            return _QRPosition("right", 20)
        if metadata.get("qr_centered") == "vertical":
            return _QRPosition("center")
        for name in ("top", "bottom"):
            key = f"qr_from_{name}"
            if key in metadata:
                return _QRPosition(name, metadata[key] if type(metadata[key]) is int else 20)
        return _QRPosition("bottom", 20)

    horizontal = overrides.qr_horizontal or axis_position("horizontal")
    vertical = overrides.qr_vertical or axis_position("vertical")
    if overrides.qr_horizontal is None and overrides.qr_vertical is None:
        effective_qr = metadata
    else:
        if horizontal.method == vertical.method == "center":
            raise QRCodePlacementError("QR cannot be centered on both axes at once")
        effective_qr = {}
        if horizontal.method == "center":
            effective_qr["qr_centered"] = "horizontal"
        else:
            effective_qr[f"qr_from_{horizontal.method}"] = horizontal.offset
        if vertical.method == "center":
            effective_qr["qr_centered"] = "vertical"
        else:
            effective_qr[f"qr_from_{vertical.method}"] = vertical.offset

    return (
        PresentationInsets(**values),
        effective_qr,
        horizontal,
        vertical,
        "decoration" if decoration.presentation_insets is not None else "inherited",
        "decoration" if decoration.qr_positioning else "default",
    )


def _set_geometry_override(
    state: DiagnosticState,
    decoration_id: str,
    *,
    inset: tuple[str, int] | None = None,
    qr_horizontal: _QRPosition | None = None,
    qr_vertical: _QRPosition | None = None,
) -> DiagnosticState:
    """Update only supplied geometry fields for one decoration."""
    overrides = dict(state.geometry_overrides).get(decoration_id, GeometryOverrides())
    insets = dict(overrides.presentation_insets)
    if inset is not None:
        insets[inset[0]] = inset[1]
    horizontal = qr_horizontal or overrides.qr_horizontal
    vertical = qr_vertical or overrides.qr_vertical
    if horizontal is not None and vertical is not None and horizontal.method == vertical.method == "center":
        if qr_horizontal is not None:
            vertical = _QRPosition("bottom", 20)
        else:
            horizontal = _QRPosition("right", 20)
    updated = GeometryOverrides(tuple(sorted(insets.items())), horizontal, vertical)
    by_decoration = dict(state.geometry_overrides)
    by_decoration[decoration_id] = updated
    return replace(state, geometry_overrides=tuple(sorted(by_decoration.items())))


def _reset_geometry_overrides(state: DiagnosticState, decoration_id: str) -> DiagnosticState:
    return replace(
        state,
        geometry_overrides=tuple((key, value) for key, value in state.geometry_overrides if key != decoration_id),
    )


def _geometry_manifest_values(configuration, decoration, overrides: GeometryOverrides | None, output_size):
    insets, qr_metadata, horizontal, vertical, _, _ = _decoration_geometry(configuration, decoration, overrides)
    resolve_presentation_geometry(output_size, insets)
    placement = resolve_qr_placement(output_size, qr_metadata)
    lines = ["presentation_insets:"]
    lines.extend(f"  {name}: {getattr(insets, name)}" for name in ("left", "right", "top", "bottom"))
    if horizontal.method == "center":
        lines.append("qr_centered: horizontal")
    else:
        lines.append(f"qr_from_{horizontal.method}: {horizontal.offset}")
    if vertical.method == "center":
        lines.append("qr_centered: vertical")
    else:
        lines.append(f"qr_from_{vertical.method}: {vertical.offset}")
    return "\n".join(lines) + "\n", placement


def _qr_axis_source(decoration, overrides: GeometryOverrides | None, axis: str) -> str:
    overrides = overrides or GeometryOverrides()
    if getattr(overrides, f"qr_{axis}") is not None:
        return "temporary"
    metadata = decoration.qr_positioning
    if axis == "horizontal":
        explicit = metadata.get("qr_centered") == "horizontal" or any(
            name in metadata for name in ("qr_from_left", "qr_from_right")
        )
    else:
        explicit = metadata.get("qr_centered") == "vertical" or any(
            name in metadata for name in ("qr_from_top", "qr_from_bottom")
        )
    return "decoration" if explicit else "default"


def _mapped_output_size(output_size: tuple[int, int], available_size: tuple[int, int]) -> tuple[int, int]:
    """Fit an output image uniformly inside an available preview rectangle."""
    width, height = output_size
    max_width, max_height = available_size
    divisor = math.gcd(width, height)
    unit_width, unit_height = width // divisor, height // divisor
    scale = min(max_width // unit_width, max_height // unit_height)
    if scale < 1:
        return 1, 1
    return unit_width * scale, unit_height * scale


def preview_size_for_screen(
    output_size: tuple[int, int],
    screen_size: tuple[int, int],
    *,
    toolbar_height: int = 64,
    window_chrome: int = 100,
    margin: int = 40,
) -> tuple[int, int]:
    """Return a uniformly scaled preview fitting the screen with toolbar and window chrome."""
    screen_width, screen_height = screen_size
    return _mapped_output_size(
        output_size,
        (
            max(1, screen_width - window_chrome - margin),
            max(1, screen_height - toolbar_height - window_chrome - margin),
        ),
    )


def preview_window_layout(
    output_size: tuple[int, int],
    screen_size: tuple[int, int],
    toolbar_size: tuple[int, int],
    *,
    status_height: int = 72,
    geometry_height: int = 0,
    geometry_width: int = 0,
    margin: int = 24,
) -> tuple[tuple[int, int], tuple[int, int, int, int]]:
    """Fit the preview and center a window that also contains its complete controls."""
    screen_width, screen_height = screen_size
    toolbar_width, toolbar_height = toolbar_size
    controls_width = max(toolbar_width, geometry_width)
    outer = 16
    available_width = max(1, screen_width - margin * 2 - outer)
    reserved_height = toolbar_height + geometry_height + status_height + margin * 2 + outer
    available_height = max(1, screen_height - reserved_height)
    preview = _mapped_output_size(output_size, (available_width, available_height))
    window_width = min(screen_width - margin, max(preview[0] + outer, controls_width + outer))
    window_height = min(screen_height - margin, preview[1] + reserved_height)
    left = max(0, (screen_width - window_width) // 2)
    top = max(0, (screen_height - window_height) // 2)
    return preview, (window_width, window_height, left, top)


def _configured_aspect_name(output_size: tuple[int, int]) -> str:
    divisor = gcd(*output_size)
    ratio = (output_size[0] // divisor, output_size[1] // divisor)
    return next(name for name, dimensions in _ASPECTS.items() if dimensions == ratio)


def transition_state(state: DiagnosticState, action: str) -> DiagnosticState:
    """Apply one named navigation or toggle action to diagnostic state."""
    if action == "next-decoration" and state.decoration_ids:
        return replace(state, decoration_index=(state.decoration_index + 1) % len(state.decoration_ids))
    if action == "previous-decoration" and state.decoration_ids:
        return replace(state, decoration_index=(state.decoration_index - 1) % len(state.decoration_ids))
    if action == "next-quotation":
        return replace(state, quotation_index=(state.quotation_index + 1) % len(_QUOTATIONS))
    if action == "previous-quotation":
        return replace(state, quotation_index=(state.quotation_index - 1) % len(_QUOTATIONS))
    if action == "next-aspect":
        ratios = tuple(_ASPECTS)
        current = state.aspect_ratio if state.aspect_ratio in _ASPECTS else "16:9"
        return replace(state, aspect_ratio=ratios[(ratios.index(current) + 1) % len(ratios)])
    if action == "toggle-qr":
        return replace(state, qr_enabled=not state.qr_enabled)
    if action == "toggle-background":
        return replace(state, background_enabled=not state.background_enabled)
    if action == "toggle-tinting":
        return replace(state, tinting_enabled=not state.tinting_enabled)
    if action == "toggle-debug":
        return replace(state, debug_layout=not state.debug_layout)
    return state


def normalize_key(key: str) -> str | None:
    """Normalize Tk, ANSI terminal, and Windows extended-key spellings."""
    if key == " ":
        return "space"
    normalized = {
        "\x1b[A": "up",
        "\x1b[B": "down",
        "\x1b[C": "right",
        "\x1b[D": "left",
        "\x1b[15~": "f5",
        "\x1b[17~": "f6",
        "\x00H": "up",
        "\xe0H": "up",
        "\x00P": "down",
        "\xe0P": "down",
        "\x00M": "right",
        "\xe0M": "right",
        "\x00K": "left",
        "\xe0K": "left",
        "\x00\x3f": "f5",
        "\xe0\x3f": "f5",
    }
    if key in normalized:
        return normalized[key]
    lowered = key.lower()
    return (
        lowered
        if lowered in {"right", "left", "up", "down", "f5", "space", "q", "b", "t", "d", "r", "x", "a"}
        else None
    )


def _guide_color(index: int, count: int) -> str:
    red, green, blue = colorsys.hsv_to_rgb(index / max(count, 1), 0.9, 1)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _guide_groups(details: PreparationDiagnostics):
    groups = {}
    for guide in details.nine_slice_guides:
        groups.setdefault((guide.x_bounds, guide.y_bounds), []).append(guide)
    return groups


def _state_action(key: str) -> str | None:
    normalized = normalize_key(key)
    return {
        "right": "next-decoration",
        "space": "next-decoration",
        "left": "previous-decoration",
        "up": "next-quotation",
        "down": "previous-quotation",
        "q": "toggle-qr",
        "b": "toggle-background",
        "t": "toggle-tinting",
        "d": "toggle-debug",
        "r": "reload",
        "f5": "reload",
        "a": "next-aspect",
        "x": "exit",
    }.get(normalized)


def _overlay_diagnostics(image: Image.Image, state: DiagnosticState, details: PreparationDiagnostics) -> Image.Image:
    if not state.debug_layout:
        return image
    literary = annotate_literary_region(image, details.geometry.output_region)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def outlined(bounds: PixelBounds, color: str, width: int = 4) -> None:
        left, top, right, bottom = bounds
        draw.rectangle((left, top, right - 1, bottom - 1), outline=color, width=width)

    if details.qr_placement is not None:
        outlined(details.qr_placement.allocation_bounds, "#000000", 8)
        outlined(details.qr_placement.allocation_bounds, _QR_COLOR, 4)

    groups = _guide_groups(details)
    for color_index, (x_bounds, y_bounds) in enumerate(groups):
        color = _guide_color(color_index, len(groups))
        for x in x_bounds[1:-1]:
            output_x = round_half_up(x * image.width, details.geometry.working_size[0])
            if 0 <= output_x < image.width:
                draw.line((output_x, 0, output_x, image.height - 1), fill="#000000", width=4)
                draw.line((output_x, 0, output_x, image.height - 1), fill=color, width=2)
        for y in y_bounds[1:-1]:
            output_y = round_half_up(y * image.height, details.geometry.working_size[1])
            if 0 <= output_y < image.height:
                draw.line((0, output_y, image.width - 1, output_y), fill="#000000", width=4)
                draw.line((0, output_y, image.width - 1, output_y), fill=color, width=2)

    if groups:
        font = ImageFont.load_default()
        entries = [
            (", ".join(f"Layer {guide.layer_index}" for guide in guides), _guide_color(index, len(groups)))
            for index, guides in enumerate(groups.values())
        ]
        line_height = 18
        text_width = max(draw.textbbox((0, 0), label, font=font)[2] for label, _ in entries)
        legend_left = 12
        legend_top = 12
        legend_right = min(image.width - 1, legend_left + text_width + 42)
        legend_bottom = min(image.height - 1, legend_top + len(entries) * line_height + 8)
        draw.rectangle((legend_left, legend_top, legend_right, legend_bottom), fill=(0, 0, 0, 210))
        for index, (label, color) in enumerate(entries):
            top = legend_top + 4 + index * line_height
            draw.line((legend_left + 6, top + 5, legend_left + 22, top + 5), fill="#FFFFFF", width=5)
            draw.line((legend_left + 6, top + 5, legend_left + 22, top + 5), fill=color, width=3)
            draw.text((legend_left + 28, top), label, font=font, fill="#FFFFFF")

    background = literary.convert("RGBA")
    try:
        result = Image.alpha_composite(background, overlay).convert(image.mode)
    finally:
        background.close()
    overlay.close()
    literary.close()
    return result


def _render(
    configuration,
    identifier,
    manifest,
    variant,
    debug_layout,
    initial_warnings=(),
    *,
    aspect_ratio="configured",
    qr_enabled: bool | None = None,
    background_enabled=True,
    tinting_enabled=True,
    diagnostics_out: list[PreparationDiagnostics] | None = None,
    geometry_overrides: GeometryOverrides | None = None,
):
    resource = _validated_decoration(configuration, identifier, manifest, initial_warnings)
    insets, qr_positioning, _, _, _, _ = _decoration_geometry(configuration, resource, geometry_overrides)
    resource = replace(
        resource,
        presentation_insets=insets,
        qr_positioning=MappingProxyType(dict(qr_positioning)),
    )
    registry = dict(configuration.decorations)
    registry[identifier] = resource
    requested_qr = configuration.qr_enabled if qr_enabled is None else qr_enabled
    qr_disabled_reason = (
        "QR generation is disabled by configuration"
        if not configuration.qr_enabled
        else "QR generation is disabled by the diagnostic setting"
    )
    configuration = replace(
        _with_aspect(replace(configuration, decorations=registry), aspect_ratio),
        qr_enabled=configuration.qr_enabled and requested_qr,
    )
    text, source, attribution = _QUOTATIONS[variant]
    quotation = Quotation(text, normalize_quotation(text))
    entry = ContentEntry(
        id="decoration-diagnostic",
        quotations=(quotation,),
        source=source,
        attribution=attribution,
        decoration=identifier,
    )
    snapshot = _build_snapshot(configuration, entry, quotation, date(2000, 1, 1))
    stages = resolve_reveal_stages(snapshot)
    resolved: list[PreparationDiagnostics] = []
    images = prepare_daily_images(
        snapshot,
        (stages[-1],),
        configuration,
        chooser=_StableChoices(identifier),
        strict_decoration=True,
        force_white_background=not background_enabled,
        forced_decoration_tint=None if tinting_enabled else (0, 0, 0),
        qr_disabled_reason=qr_disabled_reason,
        on_diagnostics=resolved.append,
    )
    image = images[0]
    if diagnostics_out is not None:
        diagnostics_out.extend(resolved)
    if not resolved:
        image.close()
        raise ApplicationError("rendering did not provide resolved diagnostic geometry")
    annotated = _overlay_diagnostics(image, DiagnosticState((identifier,), debug_layout=debug_layout), resolved[0])
    if annotated is not image:
        image.close()
    return annotated, snapshot


def _configuration_decoration_ids(configuration) -> tuple[str, ...]:
    return tuple(sorted(identifier for identifier in configuration.decorations if identifier != "none"))


def _diagnostic_status(
    state: DiagnosticState,
    configuration,
    details: PreparationDiagnostics | None,
    image_size: tuple[int, int],
    preview_size: tuple[int, int] | None = None,
) -> str:
    decoration = state.decoration or "(none)"
    position = f"{state.decoration_index + 1} of {len(state.decoration_ids)}" if state.decoration_ids else "0 of 0"
    divisor = math.gcd(*image_size)
    ratio = (
        state.aspect_ratio
        if state.aspect_ratio != "configured"
        else f"{image_size[0] // divisor}:{image_size[1] // divisor}"
    )
    qr_effective = details is not None and details.qr_placement is not None
    qr = f"requested={'on' if state.qr_enabled else 'off'}, effective={'on' if qr_effective else 'off'}"
    reason = "" if qr_effective else f", reason={details.qr_unavailable_reason if details else 'not rendered'}"
    layers = []
    if details is not None:
        groups = _guide_groups(details)
        for color_index, group_layers in enumerate(groups.values()):
            names = [f"{decoration} layer {guide.layer_index}" for guide in group_layers]
            layers.append(f"{', '.join(names)}={_guide_color(color_index, len(groups))}")
    displayed = preview_size or image_size
    manifest = configuration.decorations.get(decoration)
    manifest_path = "unavailable" if manifest is None else str(manifest.manifest)
    overrides = dict(state.geometry_overrides).get(decoration, GeometryOverrides())
    if manifest is None:
        effective_insets = configuration.presentation_insets
        inset_source = "inherited"
        qr_horizontal = qr_vertical = _QRPosition("right")
    else:
        effective_insets, _, qr_horizontal, qr_vertical, inset_source, _ = _decoration_geometry(
            configuration, manifest, overrides
        )
    inset_sources = dict(overrides.presentation_insets)
    inset_values = ", ".join(
        f"{name}={getattr(effective_insets, name)} ({'temporary' if name in inset_sources else inset_source})"
        for name in ("left", "right", "top", "bottom")
    )
    horizontal_source = "default" if manifest is None else _qr_axis_source(manifest, overrides, "horizontal")
    vertical_source = "default" if manifest is None else _qr_axis_source(manifest, overrides, "vertical")
    status = (
        f"Decoration: {decoration} ({position}); manifest: {manifest_path}\n"
        f"Quotation: {_QUOTATION_NAMES[state.quotation_index]}; aspect: {ratio}; "
        f"rendered: {image_size[0]} x {image_size[1]}; preview: {displayed[0]} x {displayed[1]}\n"
        f"Literary bounds: {details.geometry.output_region if details else 'unavailable'}; "
        f"QR: {qr}{reason}; bounds: {details.qr_placement.allocation_bounds if qr_effective else 'unavailable'}; "
        f"background: {'on' if state.background_enabled else 'white'}; "
        f"tinting: {'on' if state.tinting_enabled else 'black'}; debug: {'on' if state.debug_layout else 'off'}\n"
        f"Presentation insets (working px): {inset_values}; "
        f"QR horizontal={qr_horizontal.method} "
        f"{qr_horizontal.offset if qr_horizontal.method != 'center' else ''} ({horizontal_source}), "
        f"vertical={qr_vertical.method} {qr_vertical.offset if qr_vertical.method != 'center' else ''} "
        f"({vertical_source}); temporary overrides={'active' if overrides != GeometryOverrides() else 'none'}\n"
        f"Nine-slice guides: {', '.join(layers) if layers else 'none'}"
    )
    print(status, flush=True)
    return status


def _reconcile_state(state: DiagnosticState, configuration) -> tuple[DiagnosticState, str | None]:
    available = _configuration_decoration_ids(configuration)
    if not available:
        return replace(state, decoration_ids=(), decoration_index=0), "No usable decorations remain after reload."
    previous = state.decoration
    ids = available
    if previous in ids:
        index = ids.index(previous)
        message = None
    else:
        index = 0
        message = f"Decoration {previous!r} is no longer available; showing {ids[0]!r}."
    return replace(state, decoration_ids=ids, decoration_index=index), message


def _render_request(
    config_file: str | Path,
    state: DiagnosticState,
    configuration=None,
    reload_configuration: bool = False,
) -> _RenderedPreview:
    current_configuration = (
        _load_configuration(config_file) if configuration is None or reload_configuration else configuration
    )
    state, message = _reconcile_state(state, current_configuration)
    identifier = state.decoration
    if identifier is None:
        raise ApplicationError("no usable decorations found; add valid packages under assets/decorations and reload")
    resource = current_configuration.decorations[identifier]
    details: list[PreparationDiagnostics] = []
    image, snapshot = _render(
        current_configuration,
        identifier,
        resource.manifest,
        state.quotation_index,
        state.debug_layout,
        aspect_ratio=state.aspect_ratio,
        qr_enabled=state.qr_enabled,
        background_enabled=state.background_enabled,
        tinting_enabled=state.tinting_enabled,
        diagnostics_out=details,
        geometry_overrides=dict(state.geometry_overrides).get(identifier),
    )
    return _RenderedPreview(image, snapshot, details[0], current_configuration, state, message)


def export_decoration_png(config_file: str | Path, state: DiagnosticState, output_path: str | Path) -> Path:
    """Render one deterministic native-resolution presentation without opening a display."""
    rendered = _render_request(config_file, state, reload_configuration=True)
    rendered_size = rendered.image.size
    target = Path(output_path).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    temporary_path: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            rendered.image.save(stream, format="PNG")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    except (OSError, ValueError) as error:
        raise ApplicationError(f"cannot save diagnostic PNG to {target}: {error}") from error
    finally:
        rendered.image.close()
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass

    _diagnostic_status(
        rendered.state,
        rendered.configuration,
        rendered.diagnostics,
        rendered_size,
    )
    print(f"Diagnostic PNG saved to {target}", flush=True)
    return target


def _run_tk_preview(config_file: str | Path, state: DiagnosticState) -> None:
    try:
        import tkinter as tk
        from tkinter import ttk

        from PIL import ImageTk
    except Exception as error:
        raise ApplicationError(f"the decoration preview requires Tk support: {error}") from error

    try:
        configuration = _load_configuration(config_file)
        state, message = _reconcile_state(state, configuration)
        root = tk.Tk()
    except Exception as error:
        raise ApplicationError(f"cannot initialize the decoration preview: {error}") from error

    root.title("Refrain Decoration Preview")
    root.configure(padx=8, pady=8)
    screen_size = (root.winfo_screenwidth(), root.winfo_screenheight())
    output_configuration = _with_aspect(configuration, state.aspect_ratio)
    initial_preview, initial_geometry = preview_window_layout(output_configuration.output_size, screen_size, (720, 30))
    root.geometry(f"{initial_geometry[0]}x{initial_geometry[1]}+{initial_geometry[2]}+{initial_geometry[3]}")
    image_label = tk.Label(root, borderwidth=0)
    image_label.pack()
    toolbar = tk.Frame(root)
    toolbar.pack(anchor="center", pady=(8, 4))
    geometry_panel = tk.Frame(root, relief="groove", borderwidth=1, padx=4, pady=3)
    geometry_open = [False]
    presentation_vars = {name: tk.StringVar() for name in ("left", "right", "top", "bottom")}
    qr_horizontal_var = tk.StringVar()
    qr_vertical_var = tk.StringVar()
    qr_horizontal_offset = tk.StringVar()
    qr_vertical_offset = tk.StringVar()
    presentation_row = tk.Frame(geometry_panel)
    presentation_row.pack(fill="x")
    tk.Label(presentation_row, text="Presentation (working px):").pack(side="left", padx=(0, 4))
    presentation_entries = {}
    for name in ("left", "right", "top", "bottom"):
        tk.Label(presentation_row, text=f"{name.title()}").pack(side="left", padx=(3, 1))
        entry = tk.Entry(presentation_row, textvariable=presentation_vars[name], width=7)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda event: refresh_geometry_controls())
        entry.bind("<Return>", lambda event, field=name: apply_inset(field))
        entry.bind("<FocusOut>", lambda event, field=name: apply_inset(field))
        presentation_entries[name] = entry
    presentation_source = tk.Label(presentation_row, text="")
    presentation_source.pack(side="left", padx=5)

    qr_row = tk.Frame(geometry_panel)
    qr_row.pack(fill="x", pady=(2, 0))
    tk.Label(qr_row, text="QR horizontal:").pack(side="left")
    qr_horizontal = ttk.Combobox(
        qr_row,
        textvariable=qr_horizontal_var,
        values=("From left", "From right", "Centered"),
        state="readonly",
        width=11,
    )
    qr_horizontal.pack(side="left", padx=(2, 3))
    qr_horizontal.bind("<<ComboboxSelected>>", lambda event: apply_qr_method("horizontal"))
    qr_horizontal_entry = tk.Entry(qr_row, textvariable=qr_horizontal_offset, width=6)
    qr_horizontal_entry.pack(side="left")
    qr_horizontal_entry.bind("<KeyRelease>", lambda event: refresh_geometry_controls())
    qr_horizontal_entry.bind("<Return>", lambda event: apply_qr_offset("horizontal"))
    qr_horizontal_entry.bind("<FocusOut>", lambda event: apply_qr_offset("horizontal"))
    qr_horizontal_source = tk.Label(qr_row, text="")
    qr_horizontal_source.pack(side="left", padx=3)
    tk.Label(qr_row, text="QR vertical:").pack(side="left", padx=(8, 0))
    qr_vertical = ttk.Combobox(
        qr_row, textvariable=qr_vertical_var, values=("From top", "From bottom", "Centered"), state="readonly", width=11
    )
    qr_vertical.pack(side="left", padx=(2, 3))
    qr_vertical.bind("<<ComboboxSelected>>", lambda event: apply_qr_method("vertical"))
    qr_vertical_entry = tk.Entry(qr_row, textvariable=qr_vertical_offset, width=6)
    qr_vertical_entry.pack(side="left")
    qr_vertical_entry.bind("<KeyRelease>", lambda event: refresh_geometry_controls())
    qr_vertical_entry.bind("<Return>", lambda event: apply_qr_offset("vertical"))
    qr_vertical_entry.bind("<FocusOut>", lambda event: apply_qr_offset("vertical"))
    qr_vertical_source = tk.Label(qr_row, text="")
    qr_vertical_source.pack(side="left", padx=3)

    geometry_actions = tk.Frame(geometry_panel)
    geometry_actions.pack(fill="x", pady=(2, 0))
    reset_button = tk.Button(geometry_actions, text="Reset to manifest", command=lambda: reset_geometry())
    reset_button.pack(side="left", padx=2)
    copy_button = tk.Button(geometry_actions, text="Copy values", command=lambda: copy_geometry())
    copy_button.pack(side="left", padx=2)
    geometry_status = tk.Label(geometry_actions, text="Coordinates are working-canvas pixels.", anchor="w")
    geometry_status.pack(side="left", padx=6)
    status_var = tk.StringVar(value=message or "Rendering preview…")
    status_label = tk.Label(root, textvariable=status_var, justify="left", anchor="w")
    status_label.pack(fill="x")
    help_var = tk.StringVar(
        value=(
            "Keys: ←/→ decoration · ↑/↓ quotation · A aspect · Q QR · B background · "
            "T tint · D debug · R/F5 reload · X exit"
        )
    )
    help_label = tk.Label(root, textvariable=help_var, justify="center")
    help_label.pack(fill="x", pady=(4, 0))

    state_box = [state]
    configuration_box = [configuration]
    current_photo = [None]
    current_image = [None]
    displayed_image = [None]
    displayed_size = [None]
    last_rendered_state = [None]
    geometry_error = [None]
    bound_decoration = [None]
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refrain-decoration-preview")
    result_queue: queue.Queue[tuple[Future, DiagnosticState]] = queue.Queue()
    render_pending = [False]
    reload_pending = [False]
    rendering = [False]
    closed = [False]

    def selected_geometry():
        identifier = state_box[0].decoration
        resource = configuration_box[0].decorations.get(identifier)
        if identifier is None or resource is None:
            return None
        overrides = dict(state_box[0].geometry_overrides).get(identifier)
        return identifier, resource, overrides

    def set_geometry_error(error):
        previous_error = geometry_error[0]
        geometry_error[0] = error
        geometry_status.configure(
            text=f"Geometry validation: {error}" if error else "Coordinates are working-canvas pixels."
        )
        if error and error != previous_error:
            print(f"Decoration geometry validation: {error}", file=sys.stderr, flush=True)

    def refresh_geometry_controls(force=False):
        selected = selected_geometry()
        if selected is None:
            return
        identifier, resource, overrides = selected
        insets, _, horizontal, vertical, inset_source, _ = _decoration_geometry(
            configuration_box[0], resource, overrides
        )
        if not force and bound_decoration[0] == identifier and last_rendered_state[0] is not None:
            pass
        else:
            for name in presentation_vars:
                presentation_vars[name].set(str(getattr(insets, name)))
            qr_horizontal_var.set("Centered" if horizontal.method == "center" else f"From {horizontal.method}")
            qr_vertical_var.set("Centered" if vertical.method == "center" else f"From {vertical.method}")
            qr_horizontal_offset.set("" if horizontal.method == "center" else str(horizontal.offset))
            qr_vertical_offset.set("" if vertical.method == "center" else str(vertical.offset))
            bound_decoration[0] = identifier
            inset_overrides = dict(overrides.presentation_insets) if overrides else {}
            for name in presentation_vars:
                source = "Temporary" if name in inset_overrides else inset_source.title()
                presentation_source.configure(text=source)
            qr_horizontal_source.configure(text=_qr_axis_source(resource, overrides, "horizontal").title())
            qr_vertical_source.configure(text=_qr_axis_source(resource, overrides, "vertical").title())
        horizontal_centered = qr_horizontal_var.get() == "Centered"
        vertical_centered = qr_vertical_var.get() == "Centered"
        qr_horizontal_entry.configure(state="disabled" if horizontal_centered else "normal")
        qr_vertical_entry.configure(state="disabled" if vertical_centered else "normal")
        active = overrides is not None and overrides != GeometryOverrides()
        reset_button.configure(state="normal" if active else "disabled")
        copy_is_current = all(
            presentation_vars[name].get().strip() == str(getattr(insets, name))
            for name in ("left", "right", "top", "bottom")
        )
        copy_is_current = copy_is_current and qr_horizontal_var.get() == (
            "Centered" if horizontal.method == "center" else f"From {horizontal.method}"
        )
        copy_is_current = copy_is_current and qr_vertical_var.get() == (
            "Centered" if vertical.method == "center" else f"From {vertical.method}"
        )
        if horizontal.method != "center":
            copy_is_current = copy_is_current and qr_horizontal_offset.get().strip() == str(horizontal.offset)
        if vertical.method != "center":
            copy_is_current = copy_is_current and qr_vertical_offset.get().strip() == str(vertical.offset)
        try:
            output = _with_aspect(configuration_box[0], state_box[0].aspect_ratio).output_size
            _geometry_manifest_values(configuration_box[0], resource, overrides, output)
        except (PresentationGeometryError, QRCodePlacementError, ValueError):
            copy_button.configure(state="disabled")
        else:
            copy_button.configure(state="normal" if copy_is_current else "disabled")

    def parse_geometry_integer(value, label):
        value = value.strip()
        if not value or not value.isascii() or not value.isdigit():
            raise ValueError(f"{label} must be a nonnegative integer")
        return int(value)

    def apply_inset(name):
        try:
            value = parse_geometry_integer(presentation_vars[name].get(), f"{name.title()} inset")
            identifier, resource, _ = selected_geometry()
            current_insets, *_ = _decoration_geometry(
                configuration_box[0],
                resource,
                dict(state_box[0].geometry_overrides).get(identifier),
            )
            if value == getattr(current_insets, name):
                set_geometry_error(None)
                return "break"
            candidate = _set_geometry_override(state_box[0], identifier, inset=(name, value))
            resolved_insets, _, _, _, _, _ = _decoration_geometry(
                configuration_box[0], resource, dict(candidate.geometry_overrides).get(identifier)
            )
            output = _with_aspect(configuration_box[0], candidate.aspect_ratio).output_size
            resolve_presentation_geometry(output, resolved_insets)
        except (ValueError, PresentationGeometryError) as error:
            set_geometry_error(str(error))
            return "break"
        state_box[0] = candidate
        set_geometry_error(None)
        refresh_buttons()
        refresh_geometry_controls(force=True)
        submit_render()
        return "break"

    def apply_qr_method(axis):
        identifier, resource, overrides = selected_geometry()
        _, _, horizontal, vertical, _, _ = _decoration_geometry(configuration_box[0], resource, overrides)
        variable = qr_horizontal_var if axis == "horizontal" else qr_vertical_var
        selected = variable.get()
        method = {
            "From left": "left",
            "From right": "right",
            "From top": "top",
            "From bottom": "bottom",
            "Centered": "center",
        }[selected]
        current = horizontal if axis == "horizontal" else vertical
        position = _QRPosition(method, current.offset if method != "center" else 20)
        candidate = _set_geometry_override(
            state_box[0],
            identifier,
            qr_horizontal=position if axis == "horizontal" else None,
            qr_vertical=position if axis == "vertical" else None,
        )
        try:
            _decoration_geometry(configuration_box[0], resource, dict(candidate.geometry_overrides).get(identifier))
        except QRCodePlacementError as error:
            set_geometry_error(str(error))
            refresh_geometry_controls(force=True)
            return "break"
        state_box[0] = candidate
        set_geometry_error(None)
        refresh_geometry_controls(force=True)
        submit_render()
        return "break"

    def apply_qr_offset(axis):
        identifier, resource, overrides = selected_geometry()
        _, _, horizontal, vertical, _, _ = _decoration_geometry(configuration_box[0], resource, overrides)
        variable = qr_horizontal_offset if axis == "horizontal" else qr_vertical_offset
        current = horizontal if axis == "horizontal" else vertical
        if current.method == "center":
            return "break"
        try:
            offset = parse_geometry_integer(variable.get(), f"QR {axis} offset")
        except ValueError as error:
            set_geometry_error(str(error))
            return "break"
        if offset == current.offset:
            set_geometry_error(None)
            return "break"
        position = _QRPosition(current.method, offset)
        candidate = _set_geometry_override(
            state_box[0],
            identifier,
            qr_horizontal=position if axis == "horizontal" else None,
            qr_vertical=position if axis == "vertical" else None,
        )
        state_box[0] = candidate
        set_geometry_error(None)
        refresh_geometry_controls(force=True)
        submit_render()
        return "break"

    def reset_geometry():
        identifier = state_box[0].decoration
        if identifier is None:
            return
        state_box[0] = _reset_geometry_overrides(state_box[0], identifier)
        set_geometry_error(None)
        refresh_geometry_controls(force=True)
        submit_render()

    def copy_geometry():
        selected = selected_geometry()
        if selected is None:
            return
        identifier, resource, overrides = selected
        try:
            output = _with_aspect(configuration_box[0], state_box[0].aspect_ratio).output_size
            fragment, _ = _geometry_manifest_values(configuration_box[0], resource, overrides, output)
            root.clipboard_clear()
            root.clipboard_append(fragment)
        except Exception as error:
            set_geometry_error(f"cannot copy geometry: {error}")
            return
        set_geometry_error(None)
        geometry_status.configure(text="Manifest values copied to the clipboard.")

    def resize_preview():
        if current_image[0] is None or closed[0]:
            return (1, 1)
        root.update_idletasks()
        toolbar_size = (toolbar.winfo_reqwidth(), toolbar.winfo_reqheight())
        status_height = status_label.winfo_reqheight() + help_label.winfo_reqheight() + 24
        panel_height = geometry_panel.winfo_reqheight() if geometry_open[0] else 0
        panel_width = geometry_panel.winfo_reqwidth() if geometry_open[0] else 0
        display_size, geometry = preview_window_layout(
            current_image[0].size,
            screen_size,
            toolbar_size,
            status_height=status_height,
            geometry_height=panel_height,
            geometry_width=panel_width,
        )
        root.geometry(f"{geometry[0]}x{geometry[1]}+{geometry[2]}+{geometry[3]}")
        if displayed_image[0] is current_image[0] and displayed_size[0] == display_size:
            return display_size
        resized = current_image[0].resize(display_size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized)
        resized.close()
        image_label.configure(image=photo)
        current_photo[0] = photo
        displayed_image[0] = current_image[0]
        displayed_size[0] = display_size
        return display_size

    refresh_geometry_controls(force=True)

    def render_worker(target_state, reload_configuration):
        return _render_request(
            config_file,
            target_state,
            configuration_box[0],
            reload_configuration=reload_configuration,
        )

    def submit_render(reload_configuration=False):
        if closed[0]:
            return
        if rendering[0]:
            render_pending[0] = True
            reload_pending[0] = reload_pending[0] or reload_configuration
            status_var.set("Rendering…")
            return
        rendering[0] = True
        status_var.set("Reloading configuration and rendering…" if reload_configuration else "Rendering preview…")
        submitted_state = state_box[0]
        future = executor.submit(render_worker, submitted_state, reload_configuration)

        def finish_render(completed, selected_state=submitted_state):
            if closed[0]:
                try:
                    completed.result().image.close()
                except Exception:
                    pass
                return
            result_queue.put((completed, selected_state))

        future.add_done_callback(finish_render)

    def close_window():
        if closed[0]:
            return
        closed[0] = True
        executor.shutdown(wait=False, cancel_futures=True)
        current_photo[0] = None
        if current_image[0] is not None:
            current_image[0].close()
            current_image[0] = None
        root.destroy()

    def update_state(action, decoration_id: str | None = None):
        if action == "exit":
            close_window()
            return
        if action == "reload":
            submit_render(reload_configuration=True)
            return
        if action == "toggle-geometry":
            geometry_open[0] = not geometry_open[0]
            if geometry_open[0]:
                geometry_panel.pack(fill="x", pady=(0, 4), before=status_label)
            else:
                geometry_panel.pack_forget()
            buttons["Geometry"].configure(text=f"Geometry {'▾' if geometry_open[0] else '▸'}")
            resize_preview()
            return
        if action == "select-decoration" and decoration_id in state_box[0].decoration_ids:
            state_box[0] = replace(
                state_box[0],
                decoration_index=state_box[0].decoration_ids.index(decoration_id),
            )
        else:
            state_box[0] = transition_state(state_box[0], action)
        refresh_buttons()
        submit_render()

    button_specs = (
        ("◀D", "previous-decoration", "Previous decoration (Left)"),
        ("picker", "select-decoration", "Choose a decoration directly"),
        ("◀Q", "previous-quotation", "Previous quotation length (Down)"),
        ("QR ✓", "toggle-qr", "Toggle QR generation (Q)"),
        ("BG ✓", "toggle-background", "Toggle graphical background (B)"),
        ("Tint ✓", "toggle-tinting", "Toggle decoration tint (T)"),
        ("Debug ✓", "toggle-debug", "Toggle geometry overlays (D)"),
        ("Q▶", "next-quotation", "Next quotation length (Up)"),
        ("D▶", "next-decoration", "Next decoration (Right or Space)"),
        ("aspect", "next-aspect", "Cycle output aspect ratio (A)"),
        ("Geometry ▸", "toggle-geometry", "Show or hide geometry controls"),
        ("Reload", "reload", "Reload configuration and assets (R or F5)"),
        ("Exit", "exit", "Close the preview (X)"),
    )
    buttons = {}
    picker_value = tk.StringVar(value=state.decoration)
    picker = ttk.Combobox(
        toolbar,
        textvariable=picker_value,
        values=state.decoration_ids,
        state="readonly",
        width=16,
    )

    def refresh_buttons():
        for name, enabled in (
            ("QR", state_box[0].qr_enabled),
            ("BG", state_box[0].background_enabled),
            ("Tint", state_box[0].tinting_enabled),
            ("Debug", state_box[0].debug_layout),
        ):
            button = buttons.get(name)
            if button is not None:
                button.configure(relief="sunken" if enabled else "raised", text=f"{name} {'✓' if enabled else '—'}")
        position = (
            f"{_QUOTATION_NAMES[state_box[0].quotation_index].title()} · "
            f"{state_box[0].decoration_index + 1}/{len(state_box[0].decoration_ids)}"
        )
        indicator.configure(text=position)
        picker.configure(values=state_box[0].decoration_ids)
        picker_value.set(state_box[0].decoration or "")
        aspect_button.configure(text=state_box[0].aspect_ratio)
        buttons["Geometry"].configure(text=f"Geometry {'▾' if geometry_open[0] else '▸'}")
        refresh_geometry_controls()

    def picker_selected(_event=None):
        update_state("select-decoration", picker_value.get())

    picker.bind("<<ComboboxSelected>>", picker_selected)

    for label, action, tooltip in button_specs[:1]:
        button = tk.Button(toolbar, text=label, command=lambda selected=action: update_state(selected), takefocus=True)
        button.pack(side="left", padx=2)
        button.bind("<Enter>", lambda event, text=tooltip: help_var.set(text))
        button.bind(
            "<Leave>",
            lambda event: help_var.set(
                "Keys: ←/→ decoration · ↑/↓ quotation · A aspect · Q QR · B background · "
                "T tint · D debug · R/F5 reload · X exit"
            ),
        )
    picker.pack(side="left", padx=2)
    picker.bind("<Enter>", lambda event: help_var.set(button_specs[1][2]))
    indicator = tk.Label(toolbar, width=18, anchor="center")
    indicator.pack(side="left", padx=5)
    aspect_button = None
    for label, action, tooltip in button_specs[2:]:
        if action == "next-aspect":
            aspect_button = tk.Button(
                toolbar,
                text=state_box[0].aspect_ratio,
                command=lambda: update_state("next-aspect"),
                takefocus=True,
            )
            aspect_button.pack(side="left", padx=2)
            aspect_button.bind("<Enter>", lambda event, text=tooltip: help_var.set(text))
            continue
        button = tk.Button(toolbar, text=label, command=lambda selected=action: update_state(selected), takefocus=True)
        button.pack(side="left", padx=2)
        name = label.removesuffix(" ✓").removesuffix(" —").removesuffix(" ▸").removesuffix(" ▾")
        buttons[name] = button
        button.bind("<Enter>", lambda event, text=tooltip: help_var.set(text))
        button.bind(
            "<Leave>",
            lambda event: help_var.set(
                "Keys: ←/→ decoration · ↑/↓ quotation · A aspect · Q QR · B background · "
                "T tint · D debug · R/F5 reload · X exit"
            ),
        )
    geometry_panel.pack_forget()
    refresh_buttons()

    def key_pressed(event):
        action = _state_action(
            event.keysym if event.keysym in {"Left", "Right", "Up", "Down", "F5", "space"} else event.char
        )
        if action is not None:
            update_state(action)
            return "break"
        return None

    root.bind("<KeyPress>", key_pressed)
    root.protocol("WM_DELETE_WINDOW", close_window)

    def poll_results():
        if closed[0]:
            return
        try:
            future, submitted_state = result_queue.get_nowait()
        except queue.Empty:
            root.after(30, poll_results)
            return
        rendering[0] = False
        try:
            rendered = future.result()
            stale = render_pending[0] or state_box[0] != submitted_state
            if stale:
                rendered.image.close()
            else:
                rendered_size = rendered.image.size
                previous_image = current_image[0]
                previous_state = last_rendered_state[0]
                previous_configuration = configuration_box[0]
                current_image[0] = rendered.image
                state_box[0] = rendered.state
                configuration_box[0] = rendered.configuration
                geometry_changed = (
                    previous_state is None
                    or previous_state.decoration != rendered.state.decoration
                    or previous_state.geometry_overrides != rendered.state.geometry_overrides
                    or previous_configuration is not rendered.configuration
                )
                if geometry_changed:
                    refresh_geometry_controls(force=True)
                refresh_buttons()
                display_size = resize_preview()
                status = _diagnostic_status(
                    rendered.state,
                    rendered.configuration,
                    rendered.diagnostics,
                    rendered_size,
                    display_size,
                )
                status_var.set(f"{rendered.message}\n{status}" if rendered.message else status)
                last_rendered_state[0] = rendered.state
                resize_preview()
                if previous_image is not None:
                    previous_image.close()
        except Exception as error:
            status_var.set(f"Cannot render decoration preview: {error}")
            print(f"Cannot render decoration preview: {error}", file=sys.stderr, flush=True)
        if render_pending[0]:
            reload_requested = reload_pending[0]
            render_pending[0] = False
            reload_pending[0] = False
            submit_render(reload_configuration=reload_requested)
        if not closed[0]:
            root.after(30, poll_results)

    root.after(30, poll_results)
    submit_render(reload_configuration=True)
    try:
        root.mainloop()
    finally:
        if not closed[0]:
            close_window()


def _run_terminal_test_adapter(
    config_file: str | Path,
    state: DiagnosticState,
    debug_layout: bool,
    backend_factory: BackendFactory,
    input_factory,
) -> None:
    """Exercise the legacy terminal publication seam used by hardware-independent tests."""
    configuration = _load_configuration(config_file)
    identifiers = _configuration_decoration_ids(configuration)
    if not identifiers:
        raise ApplicationError("no usable decorations found; add valid packages under assets/decorations and restart")
    state = replace(state, decoration_ids=identifiers)
    manifests = {identifier: configuration.decorations[identifier].manifest for identifier in identifiers}
    _, initial_warnings = _discover(configuration)
    position = state.decoration_index * 2 + (state.quotation_index != 0)
    serial = 0
    with input_factory() as read_key:
        coordinator = DisplayPublicationCoordinator(configuration.display_backends, backend_factory, retry=False)
        try:
            while True:
                identifier = identifiers[position // 2]
                variant = 0 if position % 2 == 0 else 2
                print(
                    f"\nRefrain decoration diagnostic\nDecoration: {identifier}\n"
                    f"Presentation: {position + 1} of {len(identifiers) * 2}\n"
                    f"Quotation: {_QUOTATION_NAMES[variant].upper()}\nManifest: {manifests[identifier]}\n"
                    f"Debug layout: {'enabled' if debug_layout else 'disabled'}\n"
                    "SPACE/Right Next | Left Previous | Up/Down Quotation | R/F5 Reload | X Exit",
                    flush=True,
                )
                try:
                    current_configuration = _load_configuration(config_file)
                    image, snapshot = _render(
                        current_configuration,
                        identifier,
                        manifests[identifier],
                        variant,
                        debug_layout,
                        initial_warnings,
                    )
                    decoration = current_configuration.decorations.get(identifier)
                    insets = (
                        current_configuration.presentation_insets
                        if decoration is None or decoration.presentation_insets is None
                        else decoration.presentation_insets
                    )
                    geometry = resolve_presentation_geometry(current_configuration.output_size, insets)
                    print(
                        f"Rendered dimensions: {image.width} x {image.height}; "
                        f"Literary output bounds: {geometry.output_region} "
                        f"(working canvas {geometry.working_size[0]} x {geometry.working_size[1]})",
                        flush=True,
                    )
                    serial += 1
                    identity = (0, serial)
                    coordinator.publish(identity, image)
                    coordinator.wait_for_publication(identity)
                    for backend, (published, error) in coordinator.publication_results(identity).items():
                        if not published:
                            print(f"Display publication failed for {backend}: {error}", file=sys.stderr, flush=True)
                    image.close()
                except Exception as error:
                    print(
                        f"Cannot present decoration {identifier!r}: {error}; correct the files and press R",
                        file=sys.stderr,
                        flush=True,
                    )
                while True:
                    raw = read_key()
                    if not raw:
                        raise ApplicationError("terminal input ended; run the diagnostic in an interactive terminal")
                    if raw.lower() == "q" or raw == "\x03":
                        return
                    action = "previous-decoration" if raw.lower() == "b" else _state_action(raw)
                    if action == "next-decoration":
                        position = (position + 1) % (len(identifiers) * 2)
                        break
                    if action == "previous-decoration":
                        position = (position - 1) % (len(identifiers) * 2)
                        break
                    if action == "next-quotation":
                        decoration_index = position // 2
                        quotation_index = 1 - position % 2
                        position = decoration_index * 2 + quotation_index
                        break
                    if action == "previous-quotation":
                        decoration_index = position // 2
                        quotation_index = 1 - position % 2
                        position = decoration_index * 2 + quotation_index
                        break
                    if action == "reload":
                        break
        except KeyboardInterrupt:
            pass
        finally:
            coordinator.close()


def run_decoration_diagnostic(
    config_file: str | Path,
    *,
    selection: str = "all",
    aspect_ratio: str = "configured",
    quotation: str = "short",
    qr_enabled: bool | None = None,
    background_enabled: bool = True,
    tinting_enabled: bool = True,
    debug_layout: bool = False,
    output_path: str | Path | None = None,
    backend_factory: BackendFactory = _default_backend_factory,
    input_factory=None,
    preview_factory: Callable[[str | Path, DiagnosticState], None] | None = None,
) -> None:
    """Inspect one or all decorations in an isolated interactive desktop preview."""
    configuration = _load_configuration(config_file)
    available = _configuration_decoration_ids(configuration)
    if not available:
        raise ApplicationError("no usable decorations found; add valid packages under assets/decorations and restart")
    if selection == "all":
        identifiers = available
        all_decorations = True
    elif selection in available:
        identifiers = available
        all_decorations = False
    else:
        selections = ", ".join(("all", *available))
        raise ApplicationError(f"unknown decoration {selection!r}; available selections: {selections}")
    if aspect_ratio != "configured" and aspect_ratio not in _ASPECTS:
        raise ApplicationError("aspect ratio must be 4:3, 16:9, or 16:10")
    if quotation not in _QUOTATION_NAMES:
        raise ApplicationError("quotation length must be short, medium, or long")
    if output_path is not None and selection == "all":
        raise ApplicationError("--test-output requires exactly one decoration ID; 'all' cannot be exported")
    if output_path is not None and input_factory is not None:
        raise ApplicationError("--test-output cannot be combined with terminal display publication")
    if selection == "all":
        decoration_index = 0
    else:
        decoration_index = available.index(selection)
    selected_aspect = (
        aspect_ratio if aspect_ratio != "configured" else _configured_aspect_name(configuration.output_size)
    )
    state = DiagnosticState(
        identifiers,
        decoration_index=decoration_index,
        quotation_index=_QUOTATION_NAMES.index(quotation),
        aspect_ratio=selected_aspect,
        qr_enabled=configuration.qr_enabled if qr_enabled is None else qr_enabled,
        background_enabled=background_enabled,
        tinting_enabled=tinting_enabled,
        debug_layout=debug_layout,
        all_decorations=all_decorations,
    )
    if output_path is not None:
        export_decoration_png(config_file, state, output_path)
        return
    if input_factory is not None:
        _run_terminal_test_adapter(config_file, state, debug_layout, backend_factory, input_factory)
        return
    runner = _run_tk_preview if preview_factory is None else preview_factory
    runner(config_file, state)

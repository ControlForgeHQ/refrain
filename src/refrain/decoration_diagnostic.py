"""Interactive, state-isolated visual inspection of decoration presentations."""

from __future__ import annotations

import hashlib
import colorsys
import math
import os
import queue
import random
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

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
from .geometry import PixelBounds, round_half_up
from .preparation import PreparationDiagnostics, prepare_daily_images
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
            yield lambda: sys.stdin.read(1)
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

    @property
    def decoration(self) -> str | None:
        if not self.decoration_ids:
            return None
        return self.decoration_ids[self.decoration_index]


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
    height = width * aspect_height // aspect_width
    return replace(configuration, output_size=(width, height))


def _mapped_output_size(output_size: tuple[int, int], available_size: tuple[int, int]) -> tuple[int, int]:
    """Fit an output image uniformly inside an available preview rectangle."""
    width, height = output_size
    max_width, max_height = available_size
    scale = min(max_width / width, max_height / height)
    return max(1, int(width * scale)), max(1, int(height * scale))


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
        (max(1, screen_width - margin), max(1, screen_height - toolbar_height - window_chrome - margin)),
    )


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
    return lowered if lowered in {"right", "left", "up", "down", "f5", "space", "q", "b", "t", "d", "r", "x"} else None


def _guide_color(index: int, count: int) -> str:
    red, green, blue = colorsys.hsv_to_rgb(index / max(count, 1), 0.9, 1)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _guide_groups(details: PreparationDiagnostics):
    groups = {}
    for guide in details.nine_slice_guides:
        groups.setdefault((guide.x_bounds, guide.y_bounds), []).append(guide.layer)
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
        "x": "exit",
    }.get(normalized)


def _overlay_diagnostics(image: Image.Image, state: DiagnosticState, details: PreparationDiagnostics) -> Image.Image:
    if not state.debug_layout:
        return image
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def outlined(bounds: PixelBounds, color: str, width: int = 4) -> None:
        left, top, right, bottom = bounds
        draw.rectangle((left, top, right - 1, bottom - 1), outline=color, width=width)

    outlined(details.geometry.output_region, "#FF3030")
    if details.qr_placement is not None:
        outlined(details.qr_placement.allocation_bounds, _QR_COLOR, 5)

    groups = _guide_groups(details)
    for color_index, (x_bounds, y_bounds) in enumerate(groups):
        color = _guide_color(color_index, len(groups))
        for x in x_bounds[1:-1]:
            output_x = round_half_up(x * image.width, details.geometry.working_size[0])
            if 0 <= output_x < image.width:
                draw.line((output_x, 0, output_x, image.height - 1), fill=color, width=2)
        for y in y_bounds[1:-1]:
            output_y = round_half_up(y * image.height, details.geometry.working_size[1])
            if 0 <= output_y < image.height:
                draw.line((0, output_y, image.width - 1, output_y), fill=color, width=2)

    result = Image.alpha_composite(image.convert("RGBA"), overlay).convert(image.mode)
    overlay.close()
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
    qr_enabled=True,
    background_enabled=True,
    tinting_enabled=True,
    diagnostics_out: list[PreparationDiagnostics] | None = None,
):
    resource = _validated_decoration(configuration, identifier, manifest, initial_warnings)
    registry = dict(configuration.decorations)
    registry[identifier] = resource
    configuration = replace(
        _with_aspect(replace(configuration, decorations=registry), aspect_ratio),
        qr_enabled=qr_enabled,
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
    ratio = state.aspect_ratio if state.aspect_ratio != "configured" else f"{image_size[0] // divisor}:{image_size[1] // divisor}"
    qr_effective = details is not None and details.qr_placement is not None
    qr = f"requested={'on' if state.qr_enabled else 'off'}, effective={'on' if qr_effective else 'off'}"
    reason = "" if qr_effective else f", reason={details.qr_unavailable_reason if details else 'not rendered'}"
    layers = []
    if details is not None:
        resource = configuration.decorations.get(decoration)
        groups = _guide_groups(details)
        for color_index, group_layers in enumerate(groups.values()):
            names = []
            for layer in group_layers:
                index = next((i + 1 for i, candidate in enumerate(resource.layers) if candidate is layer), 0)
                names.append(f"{decoration} layer {index}")
            layers.append(f"{', '.join(names)}={_guide_color(color_index, len(groups))}")
    displayed = preview_size or image_size
    manifest = configuration.decorations.get(decoration)
    manifest_path = "unavailable" if manifest is None else str(manifest.manifest)
    status = (
        f"Decoration: {decoration} ({position}); manifest: {manifest_path}\n"
        f"Quotation: {_QUOTATION_NAMES[state.quotation_index]}; aspect: {ratio}; "
        f"rendered: {image_size[0]} x {image_size[1]}; preview: {displayed[0]} x {displayed[1]}\n"
        f"Literary bounds: {details.geometry.output_region if details else 'unavailable'}; "
        f"QR: {qr}{reason}; bounds: {details.qr_placement.allocation_bounds if qr_effective else 'unavailable'}; "
        f"background: {'on' if state.background_enabled else 'white'}; "
        f"tinting: {'on' if state.tinting_enabled else 'black'}; debug: {'on' if state.debug_layout else 'off'}\n"
        f"Nine-slice guides: {', '.join(layers) if layers else 'none'}"
    )
    print(status, flush=True)
    return status


def _reconcile_state(state: DiagnosticState, configuration) -> tuple[DiagnosticState, str | None]:
    available = _configuration_decoration_ids(configuration)
    if not available:
        return replace(state, decoration_ids=(), decoration_index=0), "No usable decorations remain after reload."
    previous = state.decoration
    if state.all_decorations:
        ids = available
    elif previous in available:
        ids = (previous,)
    else:
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
    current_configuration = _load_configuration(config_file) if configuration is None or reload_configuration else configuration
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
    )
    return _RenderedPreview(image, snapshot, details[0], current_configuration, state, message)


def _run_tk_preview(config_file: str | Path, state: DiagnosticState) -> None:
    try:
        import tkinter as tk

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
    available_size = preview_size_for_screen(output_configuration.output_size, screen_size)
    root.geometry(f"{available_size[0] + 24}x{available_size[1] + 112}")
    image_label = tk.Label(root, borderwidth=0)
    image_label.pack()
    toolbar = tk.Frame(root)
    toolbar.pack(anchor="center", pady=(8, 4))
    status_var = tk.StringVar(value=message or "Rendering preview…")
    status_label = tk.Label(root, textvariable=status_var, justify="left", anchor="w")
    status_label.pack(fill="x")
    help_var = tk.StringVar(value="Keys: ←/→ decoration · ↑/↓ quotation · Q QR · B background · T tint · D debug · R/F5 reload · X exit")
    help_label = tk.Label(root, textvariable=help_var, justify="center")
    help_label.pack(fill="x", pady=(4, 0))

    state_box = [state]
    configuration_box = [configuration]
    current_photo = [None]
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="refrain-decoration-preview")
    result_queue: queue.Queue[tuple[Future, DiagnosticState]] = queue.Queue()
    render_pending = [False]
    rendering = [False]
    closed = [False]

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
            render_pending[0] = render_pending[0] or reload_configuration
            status_var.set("Rendering…")
            return
        rendering[0] = True
        status_var.set("Reloading configuration and rendering…" if reload_configuration else "Rendering preview…")
        future = executor.submit(render_worker, state_box[0], reload_configuration)
        future.add_done_callback(lambda completed: result_queue.put((completed, state_box[0])))

    def close_window():
        if closed[0]:
            return
        closed[0] = True
        executor.shutdown(wait=False, cancel_futures=True)
        current_photo[0] = None
        root.destroy()

    def update_state(action):
        if action == "exit":
            close_window()
            return
        if action == "reload":
            submit_render(reload_configuration=True)
            return
        state_box[0] = transition_state(state_box[0], action)
        refresh_buttons()
        submit_render()

    button_specs = (
        ("◀ Decor", "previous-decoration", "Previous decoration (Left)"),
        ("◀ Quote", "previous-quotation", "Previous quotation length (Down)"),
        ("QR", "toggle-qr", "Toggle QR generation (Q)"),
        ("Background", "toggle-background", "Toggle graphical background (B)"),
        ("Tint", "toggle-tinting", "Toggle decoration tint (T)"),
        ("Debug", "toggle-debug", "Toggle geometry overlays (D)"),
        ("Quote ▶", "next-quotation", "Next quotation length (Up)"),
        ("Decor ▶", "next-decoration", "Next decoration (Right or Space)"),
        ("Reload", "reload", "Reload configuration and assets (R or F5)"),
        ("Exit", "exit", "Close the preview (X)"),
    )
    buttons = {}

    def refresh_buttons():
        for name, enabled in (
            ("QR", state_box[0].qr_enabled),
            ("Background", state_box[0].background_enabled),
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

    for label, action, tooltip in button_specs[:2]:
        button = tk.Button(toolbar, text=label, command=lambda selected=action: update_state(selected), takefocus=True)
        button.pack(side="left", padx=2)
        button.bind("<Enter>", lambda event, text=tooltip: help_var.set(text))
        button.bind("<Leave>", lambda event: help_var.set(
            "Keys: ←/→ decoration · ↑/↓ quotation · Q QR · B background · T tint · D debug · R/F5 reload · X exit"
        ))
    indicator = tk.Label(toolbar, width=18, anchor="center")
    indicator.pack(side="left", padx=5)
    for label, action, tooltip in button_specs[2:]:
        button = tk.Button(toolbar, text=label, command=lambda selected=action: update_state(selected), takefocus=True)
        button.pack(side="left", padx=2)
        name = label.removesuffix(" ✓").removesuffix(" —")
        buttons[name] = button
        button.bind("<Enter>", lambda event, text=tooltip: help_var.set(text))
        button.bind("<Leave>", lambda event: help_var.set(
            "Keys: ←/→ decoration · ↑/↓ quotation · Q QR · B background · T tint · D debug · R/F5 reload · X exit"
        ))
    refresh_buttons()

    def key_pressed(event):
        action = _state_action(event.keysym if event.keysym in {"Left", "Right", "Up", "Down", "F5", "space"} else event.char)
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
            rendered_size = rendered.image.size
            previous_image = current_photo[0]
            display_size = _mapped_output_size(rendered.image.size, available_size)
            resized = rendered.image.resize(display_size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            resized.close()
            rendered.image.close()
            image_label.configure(image=photo)
            current_photo[0] = photo
            state_box[0] = rendered.state
            configuration_box[0] = rendered.configuration
            refresh_buttons()
            status = _diagnostic_status(
                rendered.state,
                rendered.configuration,
                rendered.diagnostics,
                rendered_size,
                display_size,
            )
            status_var.set(
                f"{rendered.message}\n{status}" if rendered.message else status
            )
            if previous_image is not None:
                previous_image = None
        except Exception as error:
            status_var.set(f"Cannot render decoration preview: {error}")
            print(f"Cannot render decoration preview: {error}", file=sys.stderr, flush=True)
        if render_pending[0]:
            reload_requested = render_pending[0]
            render_pending[0] = False
            submit_render(reload_configuration=reload_requested)
        else:
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
    position = state.decoration_index * len(_QUOTATIONS) + state.quotation_index
    serial = 0
    with input_factory() as read_key:
        coordinator = DisplayPublicationCoordinator(configuration.display_backends, backend_factory, retry=False)
        try:
            while True:
                identifier = identifiers[position // len(_QUOTATIONS)]
                variant = position % len(_QUOTATIONS)
                details: list[PreparationDiagnostics] = []
                print(
                    f"\nRefrain decoration diagnostic\nDecoration: {identifier}\n"
                    f"Presentation: {position + 1} of {len(identifiers) * len(_QUOTATIONS)}\n"
                    f"Quotation: {_QUOTATION_NAMES[variant].upper()}\nManifest: {manifests[identifier]}\n"
                    f"Debug layout: {'enabled' if debug_layout else 'disabled'}\n"
                    "SPACE/Right Next | Left Previous | Up/Down Quotation | R/F5 Reload | X Exit",
                    flush=True,
                )
                try:
                    image, snapshot = _render(
                        _load_configuration(config_file),
                        identifier,
                        manifests[identifier],
                        variant,
                        debug_layout,
                        initial_warnings,
                        diagnostics_out=details,
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
                    action = _state_action(raw)
                    if action == "exit" or raw in ("\x03",):
                        return
                    if action == "next-decoration":
                        position = (position + 1) % (len(identifiers) * len(_QUOTATIONS))
                        break
                    if action == "previous-decoration":
                        position = (position - 1) % (len(identifiers) * len(_QUOTATIONS))
                        break
                    if action == "next-quotation":
                        decoration_index = position // len(_QUOTATIONS)
                        quotation_index = (position % len(_QUOTATIONS) + 1) % len(_QUOTATIONS)
                        position = decoration_index * len(_QUOTATIONS) + quotation_index
                        break
                    if action == "previous-quotation":
                        decoration_index = position // len(_QUOTATIONS)
                        quotation_index = (position % len(_QUOTATIONS) - 1) % len(_QUOTATIONS)
                        position = decoration_index * len(_QUOTATIONS) + quotation_index
                        break
                    if action == "reload":
                        break
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
        identifiers = (selection,)
        all_decorations = False
    else:
        selections = ", ".join(("all", *available))
        raise ApplicationError(f"unknown decoration {selection!r}; available selections: {selections}")
    if aspect_ratio != "configured" and aspect_ratio not in _ASPECTS:
        raise ApplicationError("aspect ratio must be 4:3, 16:9, or 16:10")
    if quotation not in _QUOTATION_NAMES:
        raise ApplicationError("quotation length must be short, medium, or long")
    state = DiagnosticState(
        identifiers,
        quotation_index=_QUOTATION_NAMES.index(quotation),
        aspect_ratio=aspect_ratio,
        qr_enabled=configuration.qr_enabled if qr_enabled is None else qr_enabled,
        background_enabled=background_enabled,
        tinting_enabled=tinting_enabled,
        debug_layout=debug_layout,
        all_decorations=all_decorations,
    )
    if input_factory is not None:
        _run_terminal_test_adapter(config_file, state, debug_layout, backend_factory, input_factory)
        return
    runner = _run_tk_preview if preview_factory is None else preview_factory
    runner(config_file, state)

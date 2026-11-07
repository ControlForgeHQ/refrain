"""Interactive, state-isolated visual inspection of decoration presentations."""

from __future__ import annotations

import hashlib
import os
import random
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from importlib.resources import files
from pathlib import Path

from .application import (
    ApplicationError,
    BackendFactory,
    _build_snapshot,
    _default_backend_factory,
    _load_configuration,
    _stage_publication_image,
)
from .assets import discover_decorations
from .config import _BUNDLED_DECORATION_IDS, _parse_presentation_region
from .content import ContentEntry, Quotation, normalize_quotation
from .display.coordinator import DisplayPublicationCoordinator
from .preparation import prepare_daily_images
from .scheduling import resolve_reveal_stages

_QUOTATIONS = (
    ("I am large, I contain multitudes.", "Song of Myself", "Walt Whitman"),
    (
        "There is no frigate like a book to take us lands away, nor any coursers like a page "
        "of prancing poetry. This traverse may the poorest take without oppress of toll; "
        "how frugal is the chariot that bears the human soul.",
        "A Book",
        "Emily Dickinson",
    ),
)


@contextmanager
def single_key_input():
    """Yield a blocking single-key reader, restoring terminal settings on exit."""
    if not sys.stdin.isatty():
        raise ApplicationError("decoration diagnostic requires an interactive terminal; run it in a terminal")
    if os.name == "nt":
        import msvcrt

        def read_windows_key():
            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                msvcrt.getwch()
                return "\x00"
            return key

        yield read_windows_key
    elif os.name == "posix":
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
    else:
        raise ApplicationError("single-key input is unsupported on this platform; use Linux or Windows")


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
        _parse_presentation_region,
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


def _render(configuration, identifier, manifest, variant, debug_layout, initial_warnings=()):
    resource = _validated_decoration(configuration, identifier, manifest, initial_warnings)
    registry = dict(configuration.decorations)
    registry[identifier] = resource
    configuration = replace(configuration, decorations=registry)
    text, source, attribution = _QUOTATIONS[variant]
    quotation = Quotation(text, normalize_quotation(text))
    entry = ContentEntry(
        id="decoration-diagnostic",
        quotations=(quotation,),
        source=source,
        attribution=attribution,
        decoration=identifier,
    )
    snapshot = _build_snapshot(configuration, entry, quotation, date(2000, 1, 1), _StableChoices(identifier))
    stages = resolve_reveal_stages(snapshot)
    image = prepare_daily_images(
        snapshot,
        (stages[-1],),
        configuration.fonts,
        configuration.backgrounds,
        registry,
        strict_decoration=True,
    )[0]
    return _stage_publication_image(image, snapshot, debug_layout), snapshot


def run_decoration_diagnostic(
    config_file: str | Path,
    *,
    debug_layout: bool = False,
    backend_factory: BackendFactory = _default_backend_factory,
    input_factory=single_key_input,
) -> None:
    """Inspect all initially discovered decorations without touching production state."""
    configuration = _load_configuration(config_file)
    identifiers = tuple(sorted(identifier for identifier in configuration.decorations if identifier != "none"))
    if not identifiers:
        raise ApplicationError("no usable decorations found; add valid packages under assets/decorations and restart")
    manifests = {identifier: configuration.decorations[identifier].manifest for identifier in identifiers}
    _, initial_warnings = _discover(configuration)
    position = 0
    serial = 0
    with input_factory() as read_key:
        coordinator = DisplayPublicationCoordinator(configuration.display_backends, backend_factory, retry=False)
        try:
            while True:
                identifier = identifiers[position // 2]
                variant = position % 2
                print(
                    f"\nRefrain decoration diagnostic\nDecoration: {identifier}\n"
                    f"Presentation: {position + 1} of {len(identifiers) * 2}\n"
                    f"Quotation: {'SHORT' if variant == 0 else 'LONG'}\nManifest: {manifests[identifier]}\n"
                    f"Debug layout: {'enabled' if debug_layout else 'disabled'}\n"
                    "SPACE Next | B Previous | R Reload | Q Quit",
                    flush=True,
                )
                try:
                    configuration = _load_configuration(config_file)
                    image, snapshot = _render(
                        configuration, identifier, manifests[identifier], variant, debug_layout, initial_warnings
                    )
                    region = snapshot.layout["presentation_region"]
                    print(
                        f"Presentation region: x={region['x']} y={region['y']} "
                        f"width={region['width']} height={region['height']}",
                        flush=True,
                    )
                    serial += 1
                    identity = (0, serial)
                    coordinator.publish(identity, image)
                    coordinator.wait_for_publication(identity)
                    for backend, (published, error) in coordinator.publication_results(identity).items():
                        if not published:
                            print(f"Display publication failed for {backend}: {error}", file=sys.stderr, flush=True)
                except Exception as error:
                    print(
                        f"Cannot present decoration {identifier!r}: {error}; correct the files and press R",
                        file=sys.stderr,
                        flush=True,
                    )
                while True:
                    key = read_key()
                    if not key:
                        raise ApplicationError("terminal input ended; run the diagnostic in an interactive terminal")
                    key = key.lower()
                    if key in ("q", "\x03"):
                        return
                    if key == " ":
                        position = (position + 1) % (len(identifiers) * 2)
                        break
                    if key == "b":
                        position = (position - 1) % (len(identifiers) * 2)
                        break
                    if key == "r":
                        break
        except KeyboardInterrupt:
            pass
        finally:
            coordinator.close()

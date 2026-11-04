"""Preparation of Refrain's application-owned startup information view."""

from __future__ import annotations

import io
import logging
import os
import platform
import re
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files

from PIL import Image, ImageDraw, ImageFont

from .config import ApplicationConfiguration
from .persistence import ResolvedFont
from .renderer import CompositionVisibility, LiteraryComposition, layout_composition, render_reveal_stages

_LOGGER = logging.getLogger(__name__)
_IMAGE_SIZE = (1600, 1200)
_PAPER = "#FAF9F5"
_INK = "#26332E"
_MUTED = "#65716B"
_BUILD_VERSION = re.compile(r"v?\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][A-Za-z0-9.-]{1,24})?\Z")
_COMMIT_HASH = re.compile(r"[0-9a-fA-F]{7,40}\Z")
_REGION_MARGIN = 92
_MIN_SUPPORTING_FONT_SIZE = 12
_QUOTATION = (
    "“The world is already full of remarkable things; we don't necessarily need to make them louder, "
    "bigger, or more complicated. Sometimes we just need to become better at noticing them.”"
)
_ATTRIBUTION = "Forge, Refrain Development Team"


class InformationViewPreparationError(ValueError):
    """Raised when the complete information view cannot be rendered."""


@dataclass(frozen=True)
class _Region:
    x: float
    y: float
    width: float
    height: float


def _read_font(name: str) -> ResolvedFont:
    resource = files("refrain").joinpath(
        "assets",
        "fonts",
        name,
        {
            "lora": "Lora-Regular.ttf",
            "source-sans-3": "SourceSans3-Regular.ttf",
        }[name],
    )
    with resource.open("rb") as font_file:
        data = font_file.read()
    ImageFont.truetype(io.BytesIO(data), size=12)
    return ResolvedFont(name, data)


def _read_logo() -> Image.Image | None:
    try:
        resource = files("refrain").joinpath("assets", "branding", "controlforge-logo.png")
        with resource.open("rb") as logo_file, Image.open(logo_file) as logo:
            logo.load()
            return logo.convert("RGBA")
    except Exception as error:
        _LOGGER.warning("ControlForge logo is unavailable; omitting it from the information view: %s", error)
        return None


def _runtime_information() -> tuple[str | None, str | None]:
    try:
        system = platform.system()
        machine = platform.machine()
        python = ".".join(str(part) for part in sys.version_info[:3])
        operating_system = " · ".join(part for part in (system, machine) if part) or None
        runtime = f"{operating_system} · Python {python}" if operating_system else f"Python {python}"
    except Exception as error:
        _LOGGER.debug("Runtime details are unavailable: %s", error)
        runtime = None

    build = os.environ.get("REFRAIN_BUILD")
    if build is not None and not _BUILD_VERSION.fullmatch(build):
        build = None
    commit = os.environ.get("REFRAIN_COMMIT")
    if commit is not None and _COMMIT_HASH.fullmatch(commit):
        build = commit[:12]
    return runtime, build


def _application_version() -> str:
    try:
        return version("refrain")
    except PackageNotFoundError:
        return "development"


def _network_information(configuration: ApplicationConfiguration) -> str | None:
    for backend in configuration.display_backends:
        if backend.type != "image-server":
            continue
        host = backend.host
        if host == "0.0.0.0" or host == "::":
            return f"HTTP image server · port {backend.port}"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{backend.port}/display/current"
    return None


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, width: int) -> tuple[str, ...]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and font.getlength(f"{line} {word}") <= width:
            line = f"{line} {word}"
            continue
        if line:
            lines.append(line)
            line = ""
        remaining = word
        while remaining and font.getlength(remaining) > width:
            split = max(
                (index for index in range(1, len(remaining) + 1) if font.getlength(remaining[:index]) <= width),
                default=1,
            )
            lines.append(remaining[:split])
            remaining = remaining[split:]
        line = remaining
    if line:
        lines.append(line)
    return tuple(lines)


def _draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_data: bytes,
    bounds: tuple[int, int, int, int],
    *,
    preferred_size: int,
    fill: str,
    right_align: bool = False,
) -> tuple[int, tuple[str, ...]]:
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    for size in range(preferred_size, _MIN_SUPPORTING_FONT_SIZE - 1, -1):
        font = ImageFont.truetype(io.BytesIO(font_data), size=size)
        lines = _wrap_to_width(text, font, width)
        line_height = max(font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines)
        spacing = max(2, size // 5)
        if (
            all(font.getlength(line) <= width for line in lines)
            and len(lines) * line_height + (len(lines) - 1) * spacing <= height
        ):
            if right_align:
                y = top
                for line in lines:
                    draw.text((right, y), line, font=font, fill=fill, anchor="rt")
                    y += line_height + spacing
            else:
                draw.multiline_text((left, top), "\n".join(lines), font=font, fill=fill, spacing=spacing)
            return size, lines
    raise ValueError(f"information text does not fit its allocated region: {text!r}")


def prepare_information_view(configuration: ApplicationConfiguration) -> Image.Image:
    """Render one complete 1600 × 1200 information image without consulting daily content or state."""
    if not isinstance(configuration, ApplicationConfiguration):
        raise InformationViewPreparationError("configuration must be an ApplicationConfiguration")

    background: Image.Image | None = None
    image: Image.Image | None = None
    logo: Image.Image | None = None
    try:
        quotation_font = _read_font("lora")
        supporting_font = _read_font("source-sans-3")
        background = Image.new("RGB", _IMAGE_SIZE, _PAPER)
        draw = ImageDraw.Draw(background)

        left = _REGION_MARGIN
        right = _IMAGE_SIZE[0] - _REGION_MARGIN
        corner_width = 530
        brand_font = ImageFont.truetype(io.BytesIO(supporting_font.data), size=34)
        draw.text((left, 76), "REFRAIN", font=brand_font, fill=_INK)
        _draw_fitted_text(
            draw,
            "Made for a quieter kind of noticing.",
            supporting_font.data,
            (left, 125, left + corner_width, 157),
            preferred_size=20,
            fill=_MUTED,
        )
        runtime, build = _runtime_information()
        version_text = f"Version {_application_version()}"
        if build:
            version_text = f"{version_text} · build {build}"
        _draw_fitted_text(
            draw,
            version_text,
            supporting_font.data,
            (left, 164, left + corner_width, 195),
            preferred_size=18,
            fill=_MUTED,
        )

        logo = _read_logo()
        if logo is not None:
            logo.thumbnail((260, 92), Image.Resampling.LANCZOS)
            background.paste(logo, (right - logo.width, 72), logo)
        _draw_fitted_text(
            draw,
            "github.com/ControlForgeHQ/refrain",
            supporting_font.data,
            (right - corner_width, 122, right, 150),
            preferred_size=17,
            fill=_MUTED,
            right_align=True,
        )
        _draw_fitted_text(
            draw,
            "© 2026 Edward Wright",
            supporting_font.data,
            (right - corner_width, 157, right, 181),
            preferred_size=14,
            fill=_MUTED,
            right_align=True,
        )

        composition = LiteraryComposition(quotation=_QUOTATION, attribution=_ATTRIBUTION)
        layout = layout_composition(
            composition,
            quotation_font,
            _Region(0.17, 0.27, 0.66, 0.40),
            _IMAGE_SIZE,
            min_font_size=26,
            max_font_size=42,
            presentation_style="centered",
        )
        rendered = render_reveal_stages(
            background,
            quotation_font,
            layout,
            (CompositionVisibility(quotation=True, attribution=True),),
        )
        background.close()
        background = None
        image = rendered[0]
        draw = ImageDraw.Draw(image)

        _draw_fitted_text(
            draw,
            "RUNNING ON",
            supporting_font.data,
            (left, 934, left + corner_width, 954),
            preferred_size=13,
            fill=_MUTED,
        )
        _draw_fitted_text(
            draw,
            "NETWORK",
            supporting_font.data,
            (left, 1018, left + corner_width, 1038),
            preferred_size=13,
            fill=_MUTED,
        )
        _draw_fitted_text(
            draw,
            "DISPLAY BACKENDS",
            supporting_font.data,
            (right - corner_width, 934, right, 954),
            preferred_size=13,
            fill=_MUTED,
            right_align=True,
        )
        left_bounds = (left, 962, left + corner_width, 1008)
        right_bounds = (right - corner_width, 962, right, 1072)
        if runtime:
            _draw_fitted_text(
                draw,
                runtime,
                supporting_font.data,
                left_bounds,
                preferred_size=18,
                fill=_MUTED,
            )
        network = _network_information(configuration)
        if network:
            _draw_fitted_text(
                draw,
                network,
                supporting_font.data,
                (left, 1046, left + corner_width, 1120),
                preferred_size=16,
                fill=_MUTED,
            )
        backend_names = ", ".join(backend.type.upper() for backend in configuration.display_backends)
        if backend_names:
            _draw_fitted_text(
                draw,
                backend_names,
                supporting_font.data,
                right_bounds,
                preferred_size=18,
                fill=_MUTED,
                right_align=True,
            )
        egg_font = ImageFont.truetype(io.BytesIO(supporting_font.data), size=8)
        egg_width = int(egg_font.getlength("1672"))
        draw.text((right - egg_width, 1085), "1672", font=egg_font, fill="#AEB6B0")
        return image
    except Exception as error:
        if background is not None:
            background.close()
        if image is not None:
            image.close()
        raise InformationViewPreparationError(f"cannot prepare information view: {error}") from error
    finally:
        if logo is not None:
            logo.close()


__all__ = ["InformationViewPreparationError", "prepare_information_view"]

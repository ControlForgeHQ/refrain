"""Preparation of Refrain's application-owned startup information view."""

from __future__ import annotations

import io
import logging
import os
import platform
import re
import sys
from dataclasses import dataclass
from datetime import datetime
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
_ACCENT = "#6E8976"
_BUILD_VERSION = re.compile(r"v?\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][A-Za-z0-9.-]{1,24})?\Z")
_COMMIT_HASH = re.compile(r"[0-9a-fA-F]{7,40}\Z")
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


def _draw_label(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, position: tuple[int, int], text: str) -> None:
    draw.text(position, text, font=font, fill=_ACCENT)


def _draw_value(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, position: tuple[int, int], text: str) -> None:
    draw.text(position, text, font=font, fill=_INK)


def prepare_information_view(configuration: ApplicationConfiguration) -> Image.Image:
    """Render one complete 1600 × 1200 information image without consulting daily content or state."""
    if not isinstance(configuration, ApplicationConfiguration):
        raise InformationViewPreparationError("configuration must be an ApplicationConfiguration")

    background: Image.Image | None = None
    image: Image.Image | None = None
    try:
        quotation_font = _read_font("lora")
        supporting_font = _read_font("source-sans-3")
        background = Image.new("RGB", _IMAGE_SIZE, _PAPER)
        draw = ImageDraw.Draw(background)

        margin = 140
        brand_font = ImageFont.truetype(io.BytesIO(supporting_font.data), size=34)
        detail_font = ImageFont.truetype(io.BytesIO(supporting_font.data), size=20)
        label_font = ImageFont.truetype(io.BytesIO(supporting_font.data), size=18)
        footer_font = ImageFont.truetype(io.BytesIO(supporting_font.data), size=18)

        draw.text((margin, 62), "REFRAIN", font=brand_font, fill=_INK)
        draw.text((margin + 190, 75), "A CONTROLFORGE PROJECT", font=label_font, fill=_MUTED)
        version_text = f"VERSION {_application_version()}"
        draw.text((margin, 131), version_text, font=label_font, fill=_MUTED)
        runtime, build = _runtime_information()
        if build:
            draw.text((margin + 260, 131), f"BUILD {build}", font=label_font, fill=_MUTED)
        draw.line((margin, 174, _IMAGE_SIZE[0] - margin, 174), fill="#D9DED8", width=2)

        composition = LiteraryComposition(quotation=_QUOTATION, attribution=_ATTRIBUTION)
        layout = layout_composition(
            composition,
            quotation_font,
            _Region(0.10, 0.19, 0.80, 0.54),
            _IMAGE_SIZE,
            min_font_size=42,
            max_font_size=72,
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

        information_top = 900
        draw.line((margin, information_top, _IMAGE_SIZE[0] - margin, information_top), fill="#D9DED8", width=2)
        network = _network_information(configuration)
        backend_names = ", ".join(backend.type.upper() for backend in configuration.display_backends)
        columns = (
            ("RUNNING ON", runtime),
            ("NETWORK", network),
            ("DISPLAY BACKENDS", backend_names or None),
        )
        column_width = (_IMAGE_SIZE[0] - 2 * margin) // len(columns)
        for index, (label, value) in enumerate(columns):
            x = margin + index * column_width
            _draw_label(draw, label_font, (x, 936), label)
            if value:
                _draw_value(draw, detail_font, (x, 970), value)
        draw.line((margin, 1040, _IMAGE_SIZE[0] - margin, 1040), fill="#D9DED8", width=1)
        copyright = f"© {datetime.now().year} ControlForgeHQ · Refrain"
        draw.text((margin, 1065), copyright, font=footer_font, fill=_MUTED)
        draw.text((margin, 1112), "Made for a quieter kind of noticing.", font=footer_font, fill=_MUTED)
        return image
    except Exception as error:
        if background is not None:
            background.close()
        if image is not None:
            image.close()
        raise InformationViewPreparationError(f"cannot prepare information view: {error}") from error


__all__ = ["InformationViewPreparationError", "prepare_information_view"]

"""Hardware-independent preparation of daily presentation images."""

from __future__ import annotations

import io
import logging
import random
from collections.abc import Callable, Mapping, Sequence

from PIL import Image, ImageFont, ImageOps

from .config import (
    ApplicationConfiguration,
    BackgroundResource,
    DecorationResource,
    FontResource,
    PresentationRegion,
    load_background_image,
    load_decoration_image,
)
from .persistence import DailySnapshot, ResolvedFont
from .qr import (
    PRODUCTION_QR_PARAMETERS,
    QRCodeGenerationError,
    composite_qr_code,
    render_qr_code,
)
from .renderer import (
    CompositionVisibility,
    LiteraryComposition,
    QuotationRenderError,
    layout_composition,
    render_reveal_stages,
)

_BACKGROUND_COLOR = "#FFFFFF"
_BYLINE_GAP_FACTOR = 1.20
_IMAGE_SIZE = (1600, 1200)
_LOGGER = logging.getLogger(__name__)


class DailyImagePreparationError(ValueError):
    """Raised when a daily snapshot cannot produce its requested images."""


def _resolve_presentation(
    snapshot: DailySnapshot,
    configuration: ApplicationConfiguration,
    decoration: DecorationResource | None,
) -> tuple[LiteraryComposition, PresentationRegion, tuple[int, int], int, int, str]:
    composition = LiteraryComposition(
        quotation=snapshot.quotation_text,
        source=snapshot.source,
        attribution=snapshot.attribution,
    )
    region = (
        configuration.presentation_region
        if decoration is None or decoration.presentation_region is None
        else decoration.presentation_region
    )
    return (
        composition,
        region,
        _IMAGE_SIZE,
        configuration.min_font_size,
        configuration.max_font_size,
        snapshot.presentation_style,
    )


def _palette_color(configuration: ApplicationConfiguration, identifier: str) -> tuple[int, int, int]:
    value = configuration.palette[identifier]
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _resolve_palette_preference(
    configuration: ApplicationConfiguration,
    levels: Sequence[tuple[str, Sequence[str] | None]],
    chooser: random.Random,
) -> tuple[str, tuple[int, int, int]]:
    for source, candidates in levels:
        if candidates is None:
            continue
        usable = tuple(dict.fromkeys(identifier for identifier in candidates if identifier in configuration.palette))
        for identifier in candidates:
            if identifier not in configuration.palette:
                _LOGGER.warning("Palette identifier %r from %s is unavailable; excluding it", identifier, source)
        if usable:
            identifier = chooser.choice(usable)
            return identifier, _palette_color(configuration, identifier)
    return "black", _palette_color(configuration, "black")


def _resolve_text_color(
    configuration: ApplicationConfiguration,
    snapshot: DailySnapshot,
    decoration: DecorationResource | None,
    chooser: random.Random,
) -> tuple[int, int, int]:
    identifier, color = _resolve_palette_preference(
        configuration,
        (
            ("content entry", snapshot.text_color),
            ("selected decoration", None if decoration is None else decoration.text_color),
            ("layout.text.colors", configuration.default_text_colors),
        ),
        chooser,
    )
    _LOGGER.debug("Resolved literary text color %s", identifier)
    return color


def _resolve_decoration_tint(
    configuration: ApplicationConfiguration,
    snapshot: DailySnapshot,
    decoration: DecorationResource | None,
    chooser: random.Random,
) -> tuple[int, int, int] | None:
    if decoration is None or not decoration.tintable:
        return None

    identifier, color = _resolve_palette_preference(
        configuration,
        (
            ("content entry", snapshot.decoration_color),
            ("selected decoration", decoration.decoration_color),
            ("layout.decorations.colors", configuration.default_decoration_colors),
        ),
        chooser,
    )
    _LOGGER.debug("Resolved decoration color %s", identifier)
    return color


def _generate_daily_background(
    image_size: tuple[int, int],
    identifier: str,
    registry: Mapping[str, BackgroundResource],
) -> Image.Image:
    base = Image.new("RGB", image_size, _BACKGROUND_COLOR)
    if identifier == "none":
        return base
    resource = registry.get(identifier)
    if resource is None:
        _LOGGER.warning("Committed background %r is unavailable; using the paper-white base", identifier)
        return base
    try:
        with load_background_image(resource) as image:
            fitted = ImageOps.fit(image, image_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            try:
                base.paste(fitted, (0, 0), fitted if fitted.mode == "RGBA" else None)
            finally:
                fitted.close()
    except Exception as error:
        _LOGGER.warning(
            "Committed background %r is unavailable or unusable; using the paper-white base: %s",
            identifier,
            error,
        )
    return base


def _apply_daily_decoration(
    background: Image.Image,
    identifier: str,
    registry: Mapping[str, DecorationResource],
    tint_rgb: tuple[int, int, int] | None = None,
    *,
    strict: bool = False,
) -> Image.Image:
    if identifier == "none":
        return background
    resource = registry.get(identifier)
    if resource is None:
        if strict:
            raise DailyImagePreparationError(f"decoration {identifier!r} is unavailable")
        _LOGGER.warning("Committed decoration %r is unavailable; omitting the overlay", identifier)
        return background
    try:
        with load_decoration_image(resource) as image:
            source = image
            tinted: Image.Image | None = None
            try:
                if tint_rgb is not None:
                    alpha = image.getchannel("A")
                    try:
                        tinted = Image.new("RGBA", image.size, (*tint_rgb, 0))
                        tinted.putalpha(alpha)
                    finally:
                        alpha.close()
                    source = tinted
                contained = ImageOps.contain(source, background.size, method=Image.Resampling.LANCZOS)
                try:
                    position = ((background.width - contained.width) // 2, (background.height - contained.height) // 2)
                    background.paste(contained, position, contained)
                finally:
                    contained.close()
            finally:
                if tinted is not None:
                    tinted.close()
    except Exception as error:
        if strict:
            raise DailyImagePreparationError(
                f"decoration {identifier!r} is unavailable or unusable: {error}"
            ) from error
        _LOGGER.warning(
            "Committed decoration %r is unavailable or unusable; omitting the overlay: %s",
            identifier,
            error,
        )
    return background


def _read_font(resource: FontResource, face: str = "regular") -> ResolvedFont:
    path = resource.faces.get(face)
    if path is None and face == "regular":
        path = resource.path
    if path is None:
        raise ValueError(f"font bundle {resource.identifier!r} does not provide face {face!r}")
    with path.open("rb") as font_file:
        identifier = resource.identifier if face == "regular" else f"{resource.identifier}:{face}"
        font = ResolvedFont(identifier, font_file.read())
    ImageFont.truetype(io.BytesIO(font.data), size=12)
    return font


def _resolve_fonts(
    snapshot: DailySnapshot,
    configuration: ApplicationConfiguration,
    decoration: DecorationResource | None,
    chooser: random.Random,
) -> dict[str, ResolvedFont]:
    candidates: list[tuple[str, str]] = []
    if snapshot.font is not None:
        candidates.append(("content entry", snapshot.font))
    if decoration is not None and decoration.font is not None:
        candidates.append(("selected decoration", decoration.font))

    resolved_bundle: FontResource | None = None
    regular: ResolvedFont | None = None
    tried: set[str] = set()
    for source, identifier in candidates:
        tried.add(identifier)
        resource = configuration.fonts.get(identifier)
        if resource is None:
            _LOGGER.warning(
                "Requested font %r from %s is unavailable; checking the next preference",
                identifier,
                source,
            )
            continue
        try:
            regular = _read_font(resource)
            resolved_bundle = resource
            break
        except Exception as error:
            _LOGGER.warning(
                "Requested font %r from %s is unusable; checking the next preference: %s",
                identifier,
                source,
                error,
            )

    if resolved_bundle is None:
        pool = tuple(identifier for identifier in configuration.default_fonts if identifier not in tried)
        while pool:
            identifier = chooser.choice(pool)
            tried.add(identifier)
            resource = configuration.fonts.get(identifier)
            if resource is not None:
                try:
                    regular = _read_font(resource)
                    resolved_bundle = resource
                    break
                except Exception as error:
                    _LOGGER.warning(
                        "Default font %r is unusable; trying another configured font: %s",
                        identifier,
                        error,
                    )
            pool = tuple(candidate for candidate in pool if candidate != identifier)
    if resolved_bundle is None or regular is None:
        raise DailyImagePreparationError(
            "cannot resolve a usable font; add a usable content-entry or decoration font preference, "
            "or configure a usable identifier in layout.fonts.default"
        )

    preference_levels = (
        snapshot.font_faces,
        {} if decoration is None else decoration.font_faces,
        resolved_bundle.font_faces,
        configuration.font_faces,
    )
    resolved = {"quotation": regular, "source": regular, "attribution": regular}
    loaded_faces = {"regular": regular}
    for role in resolved:
        face = next((level[role] for level in preference_levels if role in level), "regular")
        if face == "regular":
            continue
        if face not in loaded_faces:
            try:
                loaded_faces[face] = _read_font(resolved_bundle, face)
            except Exception as error:
                _LOGGER.warning(
                    "Preferred %s face %r is unavailable in font bundle %r; using its regular face: %s",
                    role,
                    face,
                    resolved_bundle.identifier,
                    error,
                )
                loaded_faces[face] = regular
        resolved[role] = loaded_faces[face]
    return resolved


def _resolve_decoration(
    snapshot: DailySnapshot,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
) -> tuple[str, DecorationResource | None]:
    preferred = snapshot.decoration
    if preferred == "none":
        return "none", None
    if preferred is not None:
        resource = configuration.decorations.get(preferred)
        if resource is not None:
            return preferred, resource
        _LOGGER.warning("Requested decoration %r is unavailable; using the default decoration pool", preferred)
    if not configuration.default_decorations:
        raise DailyImagePreparationError(
            "no usable decoration remains; add an available decoration preference or configure "
            "layout.decorations.default"
        )
    identifier = chooser.choice(configuration.default_decorations)
    return identifier, configuration.decorations.get(identifier)


def _resolve_background(
    snapshot: DailySnapshot,
    decoration: DecorationResource | None,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
) -> str:
    preferences = (
        ("content entry", snapshot.background),
        ("selected decoration", None if decoration is None else decoration.background),
    )
    for source, preferred in preferences:
        if preferred is None:
            continue
        if preferred == "none" or preferred in configuration.backgrounds:
            return preferred
        _LOGGER.warning(
            "Requested background %r from %s is unavailable; checking the next preference",
            preferred,
            source,
        )
    if not configuration.default_backgrounds:
        raise DailyImagePreparationError(
            "no usable background remains; add an available background preference or configure "
            "layout.backgrounds.default"
        )
    return chooser.choice(configuration.default_backgrounds)


def prepare_daily_images(
    snapshot: DailySnapshot,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    *,
    chooser: random.Random | None = None,
    strict_decoration: bool = False,
    on_resolved_region: Callable[[PresentationRegion], None] | None = None,
) -> tuple[Image.Image, ...]:
    """Prepare complete, independent images for explicit cumulative reveal stages.

    Semantic preferences from ``snapshot`` are resolved against current configuration
    and resources once for the complete stage set. Stages are never inferred from the clock.
    """
    if not isinstance(snapshot, DailySnapshot):
        raise DailyImagePreparationError("snapshot must be a DailySnapshot")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if not isinstance(configuration, ApplicationConfiguration):
        raise DailyImagePreparationError("configuration must be a validated ApplicationConfiguration")
    chooser = chooser if chooser is not None else random.Random()
    decoration_identifier, decoration = _resolve_decoration(snapshot, configuration, chooser)
    background_identifier = _resolve_background(snapshot, decoration, configuration, chooser)
    composition, region, image_size, min_font_size, max_font_size, style = _resolve_presentation(
        snapshot, configuration, decoration
    )
    if on_resolved_region is not None:
        on_resolved_region(region)
    text_color = _resolve_text_color(configuration, snapshot, decoration, chooser)
    qr_parameters = PRODUCTION_QR_PARAMETERS
    decoration_tint = _resolve_decoration_tint(configuration, snapshot, decoration, chooser)
    fonts = _resolve_fonts(snapshot, configuration, decoration, chooser)
    try:
        layout = layout_composition(
            composition,
            fonts["quotation"],
            region,
            image_size,
            min_font_size,
            max_font_size,
            style,
            byline_gap_factor=_BYLINE_GAP_FACTOR,
            source_font=fonts["source"],
            attribution_font=fonts["attribution"],
        )
        background = _generate_daily_background(image_size, background_identifier, configuration.backgrounds)
        try:
            background = _apply_daily_decoration(
                background,
                decoration_identifier,
                configuration.decorations,
                decoration_tint,
                strict=strict_decoration,
            )
            images = render_reveal_stages(
                background,
                fonts["quotation"],
                layout,
                tuple(stages),
                concealment="pixel-distortion",
                source_font=fonts["source"],
                attribution_font=fonts["attribution"],
                text_color=text_color,
            )
            qr_code = None
            try:
                qr_code = render_qr_code(qr_parameters, image_size)
                for image in images:
                    composite_qr_code(image, qr_code)
                return images
            except Exception:
                for image in images:
                    image.close()
                raise
            finally:
                if qr_code is not None:
                    qr_code.image.close()
        except QRCodeGenerationError as error:
            raise DailyImagePreparationError(f"cannot prepare daily snapshot QR code: {error}") from error
        finally:
            background.close()
    except QuotationRenderError as error:
        raise DailyImagePreparationError(f"cannot prepare daily snapshot images: {error}") from error


__all__ = ["DailyImagePreparationError", "prepare_daily_images"]

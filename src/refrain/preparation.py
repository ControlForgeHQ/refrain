"""Hardware-independent preparation of daily presentation images."""

from __future__ import annotations

import io
import logging
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType

from PIL import Image, ImageFont, ImageOps

from .config import (
    ApplicationConfiguration,
    BackgroundResource,
    DecorationLayerResource,
    DecorationResource,
    FontResource,
    load_background_image,
    load_decoration_layer_image,
)
from .geometry import (
    PixelBounds,
    PresentationGeometry,
    PresentationGeometryError,
    ResolvedOutputSpecification,
    resolve_presentation_geometry,
    round_half_up,
)
from .persistence import DailySnapshot, ResolvedFont
from .qr import (
    PRODUCTION_QR_PARAMETERS,
    QRCodeGenerationError,
    QRCodePlacement,
    QRCodePlacementError,
    composite_qr_code,
    render_qr_code,
    resolve_qr_placement,
)
from .renderer import (
    CompositionVisibility,
    LiteraryComposition,
    QuotationRenderError,
    annotate_literary_region,
    layout_composition,
    render_reveal_stages,
)

_BACKGROUND_COLOR = "#FFFFFF"
_BYLINE_GAP_FACTOR = 1.20
_LOGGER = logging.getLogger(__name__)


class DailyImagePreparationError(ValueError):
    """Raised when a daily snapshot cannot produce its requested images."""


@dataclass(frozen=True)
class NineSliceGuide:
    """Resolved nine-slice boundaries used by the decoration compositor."""

    layer: DecorationLayerResource
    layer_index: int
    x_bounds: tuple[int, ...]
    y_bounds: tuple[int, ...]


@dataclass(frozen=True)
class PreparationDiagnostics:
    """Resolved presentation details for an isolated diagnostic preview."""

    geometry: PresentationGeometry
    qr_placement: QRCodePlacement | None
    qr_unavailable_reason: str | None
    active_layers: tuple[DecorationLayerResource, ...]
    nine_slice_guides: tuple[NineSliceGuide, ...]


@dataclass(frozen=True)
class PresentationOverrides:
    """Optional explicit viewer choices with precedence above normal preferences."""

    font: str | None = None
    font_faces: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    background: str | None = None
    decoration: str | None = None
    text_color: str | None = None
    tint: str | None = None
    style: str | None = None
    qr_enabled: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "font_faces", MappingProxyType(dict(self.font_faces)))


@dataclass(frozen=True)
class _PresentationChoices:
    decoration_identifier: str
    decoration: DecorationResource | None
    background_identifier: str
    strict_background: bool
    strict_decoration: bool
    text_color: tuple[int, int, int]
    decoration_tint: tuple[int, int, int] | None
    fonts: Mapping[str, ResolvedFont]
    presentation_style: str
    qr_enabled: bool
    qr_policy_overridden: bool


def _resolve_presentation_choices(
    snapshot: DailySnapshot,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
    *,
    force_white_background: bool,
    forced_decoration_tint: tuple[int, int, int] | None,
    overrides: PresentationOverrides,
) -> _PresentationChoices:
    if not isinstance(overrides, PresentationOverrides):
        raise DailyImagePreparationError("overrides must be PresentationOverrides")
    invalid_roles = set(overrides.font_faces) - {"quotation", "source", "attribution"}
    if invalid_roles:
        raise DailyImagePreparationError(f"unsupported explicit font face roles: {', '.join(sorted(invalid_roles))}")
    decoration_identifier, decoration = _resolve_decoration(snapshot, configuration, chooser, overrides.decoration)
    background_identifier = (
        "none"
        if force_white_background
        else _resolve_background(snapshot, decoration, configuration, chooser, overrides.background)
    )
    text_color = _resolve_text_color(configuration, snapshot, decoration, chooser, overrides.text_color)
    if overrides.tint is not None and overrides.tint not in configuration.palette:
        raise DailyImagePreparationError(f"explicit decoration tint color {overrides.tint!r} is not in the palette")
    decoration_tint = _resolve_decoration_tint(
        configuration,
        snapshot,
        decoration,
        chooser,
        () if decoration is None else decoration.layers,
        (_palette_color(configuration, overrides.tint) if overrides.tint is not None else forced_decoration_tint),
    )
    fonts = _resolve_fonts(snapshot, configuration, decoration, chooser, overrides)
    style = snapshot.presentation_style if overrides.style is None else overrides.style
    if style not in {"centered", "left-aligned"}:
        raise DailyImagePreparationError(f"unsupported presentation style: {style!r}")
    if overrides.qr_enabled is not None and type(overrides.qr_enabled) is not bool:
        raise DailyImagePreparationError("explicit QR policy must be a boolean")
    return _PresentationChoices(
        decoration_identifier,
        decoration,
        background_identifier,
        overrides.background is not None and not force_white_background,
        overrides.decoration is not None and overrides.decoration != "none",
        text_color,
        decoration_tint,
        MappingProxyType(fonts),
        style,
        configuration.qr_enabled if overrides.qr_enabled is None else overrides.qr_enabled,
        overrides.qr_enabled is not None,
    )


def _resolve_presentation(
    snapshot: DailySnapshot,
    configuration: ApplicationConfiguration,
    decoration: DecorationResource | None,
    output_specification: ResolvedOutputSpecification,
    presentation_style: str,
) -> tuple[LiteraryComposition, PresentationGeometry, int, int, str]:
    composition = LiteraryComposition(
        quotation=snapshot.quotation_text,
        source=snapshot.source,
        attribution=snapshot.attribution,
    )
    insets = (
        configuration.presentation_insets
        if decoration is None or decoration.presentation_insets is None
        else decoration.presentation_insets
    )
    try:
        geometry = resolve_presentation_geometry(output_specification, insets)
    except PresentationGeometryError as error:
        raise DailyImagePreparationError(f"cannot resolve literary presentation geometry: {error}") from error
    design_width = geometry.design_canvas_size[0]
    presentation_width = geometry.presentation_canvas_size[0]
    return (
        composition,
        geometry,
        max(1, round_half_up(configuration.min_font_size * presentation_width, design_width)),
        max(1, round_half_up(configuration.max_font_size * presentation_width, design_width)),
        presentation_style,
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
    override: str | None = None,
) -> tuple[int, int, int]:
    if override is not None:
        if override not in configuration.palette:
            raise DailyImagePreparationError(f"explicit text color {override!r} is not in the palette")
        return _palette_color(configuration, override)
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
    layers: Sequence[DecorationLayerResource],
    forced_tint: tuple[int, int, int] | None = None,
) -> tuple[int, int, int] | None:
    if decoration is None or not any(decoration.tintable and layer.tintable for layer in layers):
        return None
    if forced_tint is not None:
        return forced_tint

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
    design_canvas_size: tuple[int, int],
    identifier: str,
    registry: Mapping[str, BackgroundResource],
    *,
    strict: bool = False,
) -> Image.Image:
    base = Image.new("RGB", design_canvas_size, _BACKGROUND_COLOR)
    if identifier == "none":
        return base
    resource = registry.get(identifier)
    if resource is None:
        if strict:
            raise DailyImagePreparationError(f"explicit background {identifier!r} is unavailable")
        _LOGGER.warning("Committed background %r is unavailable; using the paper-white base", identifier)
        return base
    try:
        with load_background_image(resource) as image:
            fitted = ImageOps.fit(image, design_canvas_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            try:
                base.paste(fitted, (0, 0), fitted if fitted.mode == "RGBA" else None)
            finally:
                fitted.close()
    except Exception as error:
        if strict:
            base.close()
            raise DailyImagePreparationError(
                f"explicit background {identifier!r} is unavailable or unusable: {error}"
            ) from error
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
    qr_available: bool = True,
    eligible_layers: Sequence[DecorationLayerResource] | None = None,
    on_nine_slice_guide: Callable[[DecorationLayerResource, tuple[int, ...], tuple[int, ...]], None] | None = None,
) -> Image.Image:
    if identifier == "none":
        return background
    resource = registry.get(identifier)
    if resource is None:
        if strict:
            raise DailyImagePreparationError(f"decoration {identifier!r} is unavailable")
        _LOGGER.warning("Committed decoration %r is unavailable; omitting the overlay", identifier)
        return background
    layers = _eligible_decoration_layers(resource, qr_available) if eligible_layers is None else tuple(eligible_layers)
    layer_indexes = {id(layer): index for index, layer in enumerate(resource.layers)}
    for index, layer in enumerate(layers):
        try:
            with load_decoration_layer_image(layer) as image:
                source = image
                tinted: Image.Image | None = None
                try:
                    if tint_rgb is not None and _decoration_layer_is_tintable(resource, layer):
                        if image.mode == "RGBA":
                            alpha = image.getchannel("A")
                            try:
                                tinted = Image.new("RGBA", image.size, (*tint_rgb, 0))
                                tinted.putalpha(alpha)
                            finally:
                                alpha.close()
                        else:
                            tinted = Image.new("RGB", image.size, tint_rgb)
                        source = tinted
                    if layer.method == "contain":
                        contained = ImageOps.contain(source, background.size, method=Image.Resampling.LANCZOS)
                        try:
                            position = (
                                (background.width - contained.width) // 2,
                                (background.height - contained.height) // 2,
                            )
                            _paste_decoration_region(background, contained, position)
                        finally:
                            contained.close()
                    elif layer.method == "cover":
                        _compose_cover(background, source)
                    else:
                        x_bounds, y_bounds = _compose_nine_slice(background, source, layer)
                        if on_nine_slice_guide is not None:
                            on_nine_slice_guide(layer, x_bounds, y_bounds)
                finally:
                    if tinted is not None:
                        tinted.close()
        except Exception as error:
            manifest_index = layer_indexes.get(id(layer), index)
            message = (
                f"decoration {identifier!r} layer {manifest_index} ({layer.image}) is unavailable or unusable: {error}"
            )
            if strict:
                raise DailyImagePreparationError(message) from error
            _LOGGER.warning("%s; omitting this layer", message)
    return background


def _eligible_decoration_layers(
    decoration: DecorationResource | None,
    qr_available: bool,
) -> tuple[DecorationLayerResource, ...]:
    if decoration is None:
        return ()
    return tuple(
        layer
        for layer in decoration.layers
        if layer.condition == "always"
        or (layer.condition == "qr" and qr_available)
        or (layer.condition == "no-qr" and not qr_available)
    )


def _decoration_layer_is_tintable(decoration: DecorationResource, layer: DecorationLayerResource) -> bool:
    return decoration.tintable and layer.tintable


def _paste_decoration_region(background: Image.Image, region: Image.Image, position: tuple[int, int]) -> None:
    if region.mode == "RGBA":
        background.paste(region, position, region)
    else:
        background.paste(region, position)


def _rounded_fraction(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _compose_cover(background: Image.Image, source: Image.Image) -> None:
    if source.size == background.size:
        _paste_decoration_region(background, source, (0, 0))
        return

    scale = max(Fraction(background.width, source.width), Fraction(background.height, source.height))
    scaled_size = (
        max(background.width, _rounded_fraction(source.width * scale)),
        max(background.height, _rounded_fraction(source.height * scale)),
    )
    scaled = source if scaled_size == source.size else source.resize(scaled_size, Image.Resampling.LANCZOS)
    try:
        left = (scaled.width - background.width) // 2
        top = (scaled.height - background.height) // 2
        if left or top:
            covered = scaled.crop((left, top, left + background.width, top + background.height))
            try:
                _paste_decoration_region(background, covered, (0, 0))
            finally:
                covered.close()
        else:
            _paste_decoration_region(background, scaled, (0, 0))
    finally:
        if scaled is not source:
            scaled.close()


def _mapped_boundaries(size: tuple[int, int], nine_slice) -> tuple[tuple[int, ...], tuple[int, ...]]:
    source_width, source_height = size
    source_x = (0, nine_slice.left, source_width - nine_slice.right, source_width)
    source_y = (0, nine_slice.top, source_height - nine_slice.bottom, source_height)
    return source_x, source_y


def _resize_source_region(
    source: Image.Image,
    bounds: tuple[int, int, int, int],
    size: tuple[int, int],
) -> Image.Image | None:
    width, height = size
    if width <= 0 or height <= 0:
        return None
    region = source.crop(bounds)
    try:
        if region.width <= 0 or region.height <= 0:
            raise ValueError("a nonempty destination region has no source artwork")
        return region.resize(size, Image.Resampling.LANCZOS)
    finally:
        region.close()


def _compose_nine_slice(
    background: Image.Image,
    source: Image.Image,
    layer: DecorationLayerResource,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    parameters = layer.nine_slice
    if parameters is None:
        raise ValueError("nine-slice parameters are missing")
    x_bounds, y_bounds = _mapped_boundaries(source.size, parameters)
    left_width, center_width, right_width = (
        x_bounds[1] - x_bounds[0],
        x_bounds[2] - x_bounds[1],
        x_bounds[3] - x_bounds[2],
    )
    top_height, center_height, bottom_height = (
        y_bounds[1] - y_bounds[0],
        y_bounds[2] - y_bounds[1],
        y_bounds[3] - y_bounds[2],
    )
    canvas_width, canvas_height = background.size
    if left_width + right_width > canvas_width or top_height + bottom_height > canvas_height:
        raise ValueError(
            f"preserved corners ({left_width} + {right_width} by {top_height} + {bottom_height}) "
            f"do not fit the {canvas_width} x {canvas_height} design canvas"
        )
    destination_center_width = canvas_width - left_width - right_width
    destination_center_height = canvas_height - top_height - bottom_height
    if destination_center_width and center_width == 0:
        raise ValueError("the mapped source has no center region to fill the destination width")
    if destination_center_height and center_height == 0:
        raise ValueError("the mapped source has no center region to fill the destination height")

    source_x = (0, parameters.left, source.width - parameters.right, source.width)
    source_y = (0, parameters.top, source.height - parameters.bottom, source.height)
    regions = (
        (0, 0, 1, 1, 0, 0, left_width, top_height, None),
        (
            1,
            0,
            2,
            1,
            left_width,
            0,
            destination_center_width,
            top_height,
            f"horizontal-{parameters.horizontal}",
        ),
        (2, 0, 3, 1, canvas_width - right_width, 0, right_width, top_height, None),
        (0, 1, 1, 2, 0, top_height, left_width, destination_center_height, f"vertical-{parameters.vertical}"),
        (1, 1, 2, 2, left_width, top_height, destination_center_width, destination_center_height, "center"),
        (
            2,
            1,
            3,
            2,
            canvas_width - right_width,
            top_height,
            right_width,
            destination_center_height,
            f"vertical-{parameters.vertical}",
        ),
        (0, 2, 1, 3, 0, canvas_height - bottom_height, left_width, bottom_height, None),
        (
            1,
            2,
            2,
            3,
            left_width,
            canvas_height - bottom_height,
            destination_center_width,
            bottom_height,
            f"horizontal-{parameters.horizontal}",
        ),
        (
            2,
            2,
            3,
            3,
            canvas_width - right_width,
            canvas_height - bottom_height,
            right_width,
            bottom_height,
            None,
        ),
    )
    operations: list[tuple[tuple[int, int, int, int], int, int, int, int, str | None, int, int]] = []
    for x0, y0, x1, y1, dest_x, dest_y, dest_width, dest_height, mode in regions:
        if dest_width <= 0 or dest_height <= 0:
            continue
        source_bounds = (source_x[x0], source_y[y0], source_x[x1], source_y[y1])
        if source_bounds[2] <= source_bounds[0] or source_bounds[3] <= source_bounds[1]:
            raise ValueError(f"source region {source_bounds} has no artwork for its destination")
        mapped_width = x_bounds[x1] - x_bounds[x0]
        mapped_height = y_bounds[y1] - y_bounds[y0]
        if mode == "horizontal-crop" and dest_width > mapped_width:
            raise ValueError(
                f"horizontal crop destination length {dest_width} exceeds source edge length {mapped_width}"
            )
        if mode == "vertical-crop" and dest_height > mapped_height:
            raise ValueError(
                f"vertical crop destination length {dest_height} exceeds source edge length {mapped_height}"
            )
        if mode == "horizontal-crop" and mapped_width <= 0:
            raise ValueError("horizontal crop source edge has no length")
        if mode == "vertical-crop" and mapped_height <= 0:
            raise ValueError("vertical crop source edge has no length")
        operations.append((source_bounds, dest_x, dest_y, dest_width, dest_height, mode, mapped_width, mapped_height))

    for source_bounds, dest_x, dest_y, dest_width, dest_height, mode, mapped_width, mapped_height in operations:
        if mode == "horizontal-crop":
            resized = _resize_source_region(source, source_bounds, (mapped_width, dest_height))
            if resized is None:
                continue
            try:
                crop_left = round_half_up(mapped_width - dest_width, 2)
                transformed = resized.crop((crop_left, 0, crop_left + dest_width, dest_height))
            finally:
                resized.close()
        elif mode == "vertical-crop":
            resized = _resize_source_region(source, source_bounds, (dest_width, mapped_height))
            if resized is None:
                continue
            try:
                crop_top = round_half_up(mapped_height - dest_height, 2)
                transformed = resized.crop((0, crop_top, dest_width, crop_top + dest_height))
            finally:
                resized.close()
        else:
            transformed = _resize_source_region(source, source_bounds, (dest_width, dest_height))
        if transformed is None:
            continue
        try:
            _paste_decoration_region(background, transformed, (dest_x, dest_y))
        finally:
            transformed.close()
    return (
        (0, left_width, canvas_width - right_width, canvas_width),
        (0, top_height, canvas_height - bottom_height, canvas_height),
    )


def _scale_design_composition_to_presentation(
    design_composition: Image.Image,
    presentation_canvas_size: tuple[int, int],
) -> Image.Image:
    if design_composition.size == presentation_canvas_size:
        return design_composition
    scaled = design_composition.resize(presentation_canvas_size, Image.Resampling.LANCZOS)
    design_composition.close()
    return scaled


def _resize_presentation_to_output(image: Image.Image, requested_output_size: tuple[int, int]) -> Image.Image:
    """Resize the complete presentation canvas once, after all presentation composition."""
    if image.size == requested_output_size:
        return image
    resized = image.resize(requested_output_size, Image.Resampling.LANCZOS)
    image.close()
    return resized


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
    overrides: PresentationOverrides,
) -> dict[str, ResolvedFont]:
    candidates: list[tuple[str, str]] = []
    if snapshot.font is not None:
        candidates.append(("content entry", snapshot.font))
    if decoration is not None and decoration.font is not None:
        candidates.append(("selected decoration", decoration.font))

    resolved_bundle: FontResource | None = None
    regular: ResolvedFont | None = None
    tried: set[str] = set()
    if overrides.font is not None:
        resource = configuration.fonts.get(overrides.font)
        if resource is None:
            raise DailyImagePreparationError(f"explicit font {overrides.font!r} is not registered")
        try:
            regular = _read_font(resource)
        except Exception as error:
            raise DailyImagePreparationError(f"explicit font {overrides.font!r} is unusable: {error}") from error
        resolved_bundle = resource
    for source, identifier in (() if overrides.font is not None else candidates):
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
        overrides.font_faces,
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
                if role in overrides.font_faces:
                    raise DailyImagePreparationError(
                        f"explicit {role} face {face!r} is unavailable in font bundle "
                        f"{resolved_bundle.identifier!r}: {error}"
                    ) from error
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
    override: str | None = None,
) -> tuple[str, DecorationResource | None]:
    if override is not None:
        if override == "none":
            return "none", None
        resource = configuration.decorations.get(override)
        if resource is None:
            raise DailyImagePreparationError(f"explicit decoration {override!r} is not registered")
        return override, resource
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
    override: str | None = None,
) -> str:
    if override is not None:
        if override == "none":
            return "none"
        if override not in configuration.backgrounds:
            raise DailyImagePreparationError(f"explicit background {override!r} is not registered")
        return override
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


def _prepare_daily_images_for_specification(
    snapshot: DailySnapshot,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    output_specification: ResolvedOutputSpecification,
    choices: _PresentationChoices,
    *,
    strict_decoration: bool = False,
    on_resolved_bounds: Callable[[ResolvedOutputSpecification, PixelBounds], None] | None = None,
    debug_layout: bool = False,
    qr_disabled_reason: str | None = None,
    on_diagnostics: Callable[[ResolvedOutputSpecification, PreparationDiagnostics], None] | None = None,
    on_presentation_image: (
        Callable[[ResolvedOutputSpecification, Image.Image, PreparationDiagnostics], None] | None
    ) = None,
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
    if not isinstance(output_specification, ResolvedOutputSpecification):
        raise DailyImagePreparationError("output_specification must be a ResolvedOutputSpecification")
    decoration_identifier = choices.decoration_identifier
    decoration = choices.decoration
    composition, geometry, min_font_size, max_font_size, style = _resolve_presentation(
        snapshot, configuration, decoration, output_specification, choices.presentation_style
    )
    presentation_canvas_size = geometry.presentation_canvas_size
    qr_placement: QRCodePlacement | None = None
    qr_unavailable_reason: str | None = None
    if choices.qr_enabled and (decoration is None or decoration.qr_ready):
        try:
            qr_placement = resolve_qr_placement(
                output_specification,
                None if decoration is None else decoration.qr_positioning,
            )
        except QRCodePlacementError as error:
            qr_unavailable_reason = str(error)
            _LOGGER.warning("QR generation is disabled for this preparation: %s", error)
    elif not choices.qr_enabled:
        qr_unavailable_reason = qr_disabled_reason or (
            "QR generation is disabled by viewer override"
            if choices.qr_policy_overridden
            else "QR generation is disabled by configuration"
        )
    else:
        qr_unavailable_reason = f"decoration {decoration.identifier!r} is not marked qr_ready"
    decoration_layers = _eligible_decoration_layers(decoration, qr_placement is not None)
    if on_resolved_bounds is not None:
        on_resolved_bounds(output_specification, geometry.presentation_literary_bounds)
    text_color = choices.text_color
    qr_parameters = PRODUCTION_QR_PARAMETERS
    decoration_tint = choices.decoration_tint
    nine_slice_guides: list[NineSliceGuide] = []

    def collect_nine_slice_guide(
        layer: DecorationLayerResource, x_bounds: tuple[int, ...], y_bounds: tuple[int, ...]
    ) -> None:
        layer_index = next(index for index, candidate in enumerate(decoration.layers, start=1) if candidate is layer)
        nine_slice_guides.append(NineSliceGuide(layer, layer_index, x_bounds, y_bounds))

    fonts = choices.fonts
    try:
        background_arguments = (
            geometry.design_canvas_size,
            choices.background_identifier,
            configuration.backgrounds,
        )
        background = (
            _generate_daily_background(*background_arguments, strict=True)
            if choices.strict_background
            else _generate_daily_background(*background_arguments)
        )
        try:
            background = _apply_daily_decoration(
                background,
                decoration_identifier,
                configuration.decorations,
                decoration_tint,
                strict=strict_decoration or choices.strict_decoration,
                qr_available=qr_placement is not None,
                eligible_layers=decoration_layers,
                on_nine_slice_guide=(
                    collect_nine_slice_guide
                    if on_diagnostics is not None or on_presentation_image is not None
                    else None
                ),
            )
            background = _scale_design_composition_to_presentation(background, presentation_canvas_size)
            layout = layout_composition(
                composition,
                fonts["quotation"],
                geometry.presentation_literary_bounds,
                presentation_canvas_size,
                min_font_size,
                max_font_size,
                style,
                byline_gap_factor=_BYLINE_GAP_FACTOR,
                source_font=fonts["source"],
                attribution_font=fonts["attribution"],
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
                if qr_placement is not None:
                    qr_code = render_qr_code(qr_parameters, presentation_canvas_size, qr_placement)
                    for image in images:
                        composite_qr_code(image, qr_code)
                if debug_layout:
                    annotated_images = []
                    for image in images:
                        annotated = annotate_literary_region(image, geometry.presentation_literary_bounds)
                        if annotated is not image:
                            image.close()
                        annotated_images.append(annotated)
                    images = tuple(annotated_images)
                diagnostics = PreparationDiagnostics(
                    geometry,
                    qr_placement,
                    qr_unavailable_reason,
                    tuple(decoration_layers),
                    tuple(nine_slice_guides),
                )
                if on_diagnostics is not None:
                    on_diagnostics(output_specification, diagnostics)
                if on_presentation_image is not None:
                    for image in images:
                        on_presentation_image(output_specification, image, diagnostics)
                return tuple(_resize_presentation_to_output(image, geometry.requested_output_size) for image in images)
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


def prepare_daily_images(
    snapshot: DailySnapshot,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    output_specifications: Sequence[ResolvedOutputSpecification],
    *,
    chooser: random.Random | None = None,
    strict_decoration: bool = False,
    on_resolved_bounds: Callable[[ResolvedOutputSpecification, PixelBounds], None] | None = None,
    force_white_background: bool = False,
    forced_decoration_tint: tuple[int, int, int] | None = None,
    overrides: PresentationOverrides | None = None,
    debug_layout: bool = False,
    qr_disabled_reason: str | None = None,
    on_diagnostics: Callable[[ResolvedOutputSpecification, PreparationDiagnostics], None] | None = None,
    on_presentation_image: (
        Callable[[ResolvedOutputSpecification, Image.Image, PreparationDiagnostics], None] | None
    ) = None,
) -> Mapping[ResolvedOutputSpecification, tuple[Image.Image, ...]]:
    """Prepare complete reveal-stage image variants for all required output specifications."""
    if not isinstance(snapshot, DailySnapshot):
        raise DailyImagePreparationError("snapshot must be a DailySnapshot")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if not isinstance(configuration, ApplicationConfiguration):
        raise DailyImagePreparationError("configuration must be a validated ApplicationConfiguration")
    if not isinstance(output_specifications, Sequence) or isinstance(output_specifications, (str, bytes)):
        raise DailyImagePreparationError("output_specifications must be a nonempty sequence")
    if not output_specifications or any(
        not isinstance(specification, ResolvedOutputSpecification) for specification in output_specifications
    ):
        raise DailyImagePreparationError("output_specifications must contain resolved specifications")
    unique_specifications = tuple(
        sorted(
            set(output_specifications),
            key=lambda specification: (specification.aspect_ratio, specification.requested_output_size),
        )
    )
    results: dict[ResolvedOutputSpecification, tuple[Image.Image, ...]] = {}
    chooser = chooser if chooser is not None else random.Random()
    choices = _resolve_presentation_choices(
        snapshot,
        configuration,
        chooser,
        force_white_background=force_white_background,
        forced_decoration_tint=forced_decoration_tint,
        overrides=PresentationOverrides() if overrides is None else overrides,
    )
    try:
        for output_specification in unique_specifications:
            results[output_specification] = _prepare_daily_images_for_specification(
                snapshot,
                stages,
                configuration,
                output_specification,
                choices,
                strict_decoration=strict_decoration,
                on_resolved_bounds=on_resolved_bounds,
                debug_layout=debug_layout,
                qr_disabled_reason=qr_disabled_reason,
                on_diagnostics=on_diagnostics,
                on_presentation_image=on_presentation_image,
            )
    except Exception:
        for images in results.values():
            for image in images:
                image.close()
        raise
    return MappingProxyType(results)


__all__ = [
    "DailyImagePreparationError",
    "NineSliceGuide",
    "PreparationDiagnostics",
    "PresentationOverrides",
    "prepare_daily_images",
]

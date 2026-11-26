"""Hardware-independent preparation of daily presentation images."""

from __future__ import annotations

import io
import logging
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from importlib.resources import files
from types import MappingProxyType

from PIL import Image, ImageFont, ImageOps

from .assets import valid_identifier
from .config import (
    ApplicationConfiguration,
    BackgroundResource,
    CompositionLayerResource,
    DecorationLayerResource,
    DecorationResource,
    DestinationPresentation,
    FontResource,
    PreparedImageVariantKey,
    load_background_image,
    load_composition_layer_image,
    load_decoration_layer_image,
)
from .geometry import (
    PixelBounds,
    PresentationGeometry,
    PresentationGeometryError,
    PresentationInsets,
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
    layout_composition,
    render_reveal_stages,
)

_BACKGROUND_COLOR = "#FFFFFF"
_BYLINE_GAP_FACTOR = 1.20
_LOGGER = logging.getLogger(__name__)


class DailyImagePreparationError(ValueError):
    """Raised when a daily snapshot cannot produce its requested images."""


@dataclass(frozen=True)
class _UncommittedLiteraryContent:
    """Literary rendering inputs without selection identity or persistent state."""

    quotation_text: str
    source: str | None
    attribution: str | None
    presentation_style: str = "centered"
    font: str | None = None
    font_faces: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    background: str | None = None
    decoration: str | None = None
    text_color: tuple[str, ...] | None = None
    decoration_color: tuple[str, ...] | None = None


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
    min_font_size: int | None = None
    max_font_size: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "font_faces", MappingProxyType(dict(self.font_faces)))


@dataclass(frozen=True)
class ResolvedPresentation:
    """Stable published presentation choices to resolve against installed resources."""

    background: str
    decoration: str
    font_bundle: str
    font_faces: Mapping[str, str]
    text_color: str
    decoration_color: str | None
    presentation_style: str
    qr_enabled: bool
    min_font_size: int
    max_font_size: int
    insets: PresentationInsets

    def __post_init__(self) -> None:
        faces = dict(self.font_faces)
        if set(faces) != {"quotation", "source", "attribution"}:
            raise ValueError("resolved presentation must provide all literary font faces")
        object.__setattr__(self, "font_faces", MappingProxyType(faces))


@dataclass(frozen=True)
class _PresentationChoices:
    decoration_identifier: str
    decoration: DecorationResource | None
    background_identifier: str
    strict_background: bool
    strict_decoration: bool
    text_color: tuple[int, int, int]
    text_color_identifier: str
    decoration_tint: tuple[int, int, int] | None
    decoration_color_identifier: str | None
    fonts: Mapping[str, ResolvedFont]
    presentation_style: str
    qr_enabled: bool
    qr_policy_overridden: bool


def _resolve_presentation_choices(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
    *,
    force_white_background: bool,
    forced_decoration_tint: tuple[int, int, int] | None,
    overrides: PresentationOverrides,
    destination_presentation: DestinationPresentation = DestinationPresentation(),
    resolved_presentation: ResolvedPresentation | None = None,
) -> _PresentationChoices:
    if not isinstance(overrides, PresentationOverrides):
        raise DailyImagePreparationError("overrides must be PresentationOverrides")
    invalid_roles = set(overrides.font_faces) - {"quotation", "source", "attribution"}
    if invalid_roles:
        raise DailyImagePreparationError(f"unsupported explicit font face roles: {', '.join(sorted(invalid_roles))}")
    if resolved_presentation is not None:
        return _resolve_published_presentation_choices(
            snapshot,
            configuration,
            chooser,
            overrides,
            resolved_presentation,
            force_white_background=force_white_background,
        )
    decoration_identifier, decoration = _resolve_decoration(
        snapshot,
        configuration,
        chooser,
        overrides.decoration,
        destination_presentation.decoration,
    )
    background_identifier = (
        "none"
        if force_white_background
        else _resolve_background(
            snapshot,
            decoration,
            configuration,
            chooser,
            overrides.background,
            destination_presentation.background,
        )
    )
    background = configuration.backgrounds.get(background_identifier)
    text_color_identifier = "black"
    decoration_color_identifier: str | None = None

    def remember_text_color(identifier: str) -> None:
        nonlocal text_color_identifier
        text_color_identifier = identifier

    def remember_decoration_color(identifier: str) -> None:
        nonlocal decoration_color_identifier
        decoration_color_identifier = identifier

    text_color = _resolve_text_color(
        configuration,
        snapshot,
        decoration,
        background,
        chooser,
        overrides.text_color,
        destination_presentation.text_color,
        on_resolved_identifier=remember_text_color,
    )
    tint_identifier = (
        None
        if overrides.tint is None
        else _strict_pool_override(
            overrides.tint,
            configuration.decoration_color_pools,
            configuration.palette,
            "decoration tint color",
            chooser,
        )
    )
    if tint_identifier is not None and tint_identifier not in configuration.palette:
        raise DailyImagePreparationError(f"explicit decoration tint color {tint_identifier!r} is not in the palette")
    decoration_color_identifier = tint_identifier
    decoration_tint = _resolve_decoration_tint(
        configuration,
        snapshot,
        decoration,
        chooser,
        () if decoration is None else decoration.layers,
        (_palette_color(configuration, tint_identifier) if tint_identifier is not None else forced_decoration_tint),
        background,
        destination_presentation.decoration_color,
        on_resolved_identifier=remember_decoration_color,
    )
    if decoration_tint is None:
        decoration_color_identifier = None
    fonts = _resolve_fonts(snapshot, configuration, decoration, chooser, overrides, destination_presentation)
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
        text_color_identifier,
        decoration_tint,
        decoration_color_identifier,
        MappingProxyType(fonts),
        style,
        (
            destination_presentation.qr_enabled
            if overrides.qr_enabled is None and destination_presentation.qr_enabled is not None
            else True if overrides.qr_enabled is None else overrides.qr_enabled
        ),
        overrides.qr_enabled is not None or destination_presentation.qr_enabled is not None,
    )


def _presentation_document(
    choices: _PresentationChoices,
    configuration: ApplicationConfiguration,
    overrides: PresentationOverrides,
) -> dict[str, object]:
    insets = (
        configuration.presentation_insets
        if choices.decoration is None or choices.decoration.presentation_insets is None
        else choices.decoration.presentation_insets
    )
    return {
        "style": choices.presentation_style,
        "background": choices.background_identifier,
        "decoration": choices.decoration_identifier,
        "fonts": {
            "bundle": choices.fonts["quotation"].identifier.split(":", 1)[0],
            "faces": {
                role: font.identifier.split(":", 1)[1] if ":" in font.identifier else "regular"
                for role, font in choices.fonts.items()
            },
        },
        "colors": {"text": choices.text_color_identifier, "decoration": choices.decoration_color_identifier},
        "font_size_range": {
            "minimum": configuration.min_font_size if overrides.min_font_size is None else overrides.min_font_size,
            "maximum": configuration.max_font_size if overrides.max_font_size is None else overrides.max_font_size,
        },
        "insets": {side: getattr(insets, side) for side in ("left", "right", "top", "bottom")},
    }


def resolve_canonical_presentation(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    *,
    chooser: random.Random | None = None,
    overrides: PresentationOverrides | None = None,
) -> dict[str, object]:
    """Resolve destination-independent artistic choices without rendering or persistence."""
    if not isinstance(snapshot, (DailySnapshot, _UncommittedLiteraryContent)) or not isinstance(
        configuration, ApplicationConfiguration
    ):
        raise DailyImagePreparationError("canonical resolution requires a snapshot and validated configuration")
    effective_overrides = overrides if overrides is not None else PresentationOverrides()
    choices = _resolve_presentation_choices(
        snapshot,
        configuration,
        chooser if chooser is not None else random.Random(),
        force_white_background=False,
        forced_decoration_tint=None,
        overrides=effective_overrides,
    )
    document = _presentation_document(choices, configuration, effective_overrides)
    bounds = document["font_size_range"]
    if (
        type(bounds["minimum"]) is not int
        or type(bounds["maximum"]) is not int
        or bounds["minimum"] <= 0
        or bounds["maximum"] < bounds["minimum"]
    ):
        raise DailyImagePreparationError("invalid effective font-size range")
    return document


def _resolved_from_document(document: Mapping[str, object]) -> ResolvedPresentation:
    try:
        fonts = document["fonts"]
        colors = document["colors"]
        bounds = document["font_size_range"]
        insets = document["insets"]
        return ResolvedPresentation(
            background=document["background"],
            decoration=document["decoration"],
            font_bundle=fonts["bundle"],
            font_faces=fonts["faces"],
            text_color=colors["text"],
            decoration_color=colors["decoration"],
            presentation_style=document["style"],
            qr_enabled=True,
            min_font_size=bounds["minimum"],
            max_font_size=bounds["maximum"],
            insets=PresentationInsets(**insets),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DailyImagePreparationError(f"invalid canonical presentation: {error}") from error


def _resolve_effective_choices(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
    canonical: ResolvedPresentation,
    destination: DestinationPresentation,
    overrides: PresentationOverrides,
) -> tuple[_PresentationChoices, ResolvedPresentation]:
    decoration_id = overrides.decoration or destination.decoration or canonical.decoration
    decoration = configuration.decorations.get(decoration_id) if decoration_id != "none" else None
    if decoration_id != "none" and decoration is None:
        if overrides.decoration is not None:
            raise DailyImagePreparationError(f"explicit decoration {decoration_id!r} is unavailable")
        _LOGGER.warning("Canonical decoration %r is unavailable; using no decoration", decoration_id)
        decoration_id = "none"
    background_id = overrides.background or destination.background or canonical.background
    if background_id != "none" and background_id not in configuration.backgrounds:
        if overrides.background is not None:
            raise DailyImagePreparationError(f"explicit background {background_id!r} is unavailable")
        _LOGGER.warning("Canonical background %r is unavailable; using paper white", background_id)
        background_id = "none"

    def effective_color(value: str, explicit: bool, label: str) -> str:
        if value in configuration.palette:
            return value
        if explicit:
            raise DailyImagePreparationError(f"explicit {label} {value!r} is unavailable")
        _LOGGER.warning("%s %r is unavailable; using black", label, value)
        return "black"

    text_override = overrides.text_color or destination.text_color
    if isinstance(text_override, tuple):
        text_override = text_override[0]
    text = effective_color(text_override or canonical.text_color, overrides.text_color is not None, "text color")
    tint_override = overrides.tint or destination.decoration_color
    if isinstance(tint_override, tuple):
        tint_override = tint_override[0]
    tintable = decoration is not None and any(
        _decoration_layer_is_tintable(decoration, layer) for layer in decoration.layers
    )
    tint = tint_override or canonical.decoration_color
    if tintable and tint is None and overrides.decoration is not None:
        raise DailyImagePreparationError("explicit tint is required for a tintable decoration")
    if tintable and tint is not None:
        tint = effective_color(tint, overrides.tint is not None, "decoration color")
    else:
        tint = None

    font_id = overrides.font or destination.font or canonical.font_bundle
    roles = (
        dict(canonical.font_faces) if overrides.font is None and destination.font is None else dict(snapshot.font_faces)
    )
    roles.update(overrides.font_faces)
    font_snapshot = replace(snapshot, font=font_id, font_faces=roles)
    font_overrides = PresentationOverrides(font=overrides.font, font_faces=overrides.font_faces)
    fonts = _resolve_fonts(font_snapshot, configuration, decoration, chooser, font_overrides, recovery_only=True)
    insets = canonical.insets
    if decoration_id != canonical.decoration:
        insets = (
            configuration.presentation_insets
            if decoration is None or decoration.presentation_insets is None
            else decoration.presentation_insets
        )
    effective = replace(canonical, insets=insets)
    return (
        _PresentationChoices(
            decoration_id,
            decoration,
            background_id,
            overrides.background is not None,
            overrides.decoration is not None,
            _palette_color(configuration, text),
            text,
            None if tint is None else _palette_color(configuration, tint),
            tint,
            MappingProxyType(fonts),
            overrides.style or canonical.presentation_style,
            overrides.qr_enabled is not False and destination.qr_enabled is not False,
            overrides.qr_enabled is not None or destination.qr_enabled is not None,
        ),
        effective,
    )


def _resolve_published_presentation_choices(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
    overrides: PresentationOverrides,
    resolved: ResolvedPresentation,
    *,
    force_white_background: bool,
) -> _PresentationChoices:
    if resolved.decoration == "none" and overrides.decoration is None:
        decoration_identifier, decoration = "none", None
    elif overrides.decoration is not None:
        decoration_identifier, decoration = _resolve_decoration(snapshot, configuration, chooser, overrides.decoration)
    else:
        decoration = configuration.decorations.get(resolved.decoration)
        if decoration is None:
            raise DailyImagePreparationError(
                f"published decoration {resolved.decoration!r} is unavailable; install or register that resource"
            )
        decoration_identifier = resolved.decoration

    if force_white_background:
        background_identifier = "none"
        strict_background = False
    elif overrides.background is not None:
        background_identifier = _resolve_background(snapshot, decoration, configuration, chooser, overrides.background)
        strict_background = True
    elif resolved.background == "none":
        background_identifier = "none"
        strict_background = True
    else:
        if resolved.background not in configuration.backgrounds:
            raise DailyImagePreparationError(
                f"published background {resolved.background!r} is unavailable; install or register that resource"
            )
        background_identifier = resolved.background
        strict_background = True
    if overrides.text_color is not None:
        text_color_identifier = _strict_pool_override(
            overrides.text_color,
            configuration.text_color_pools,
            configuration.palette,
            "text color",
            chooser,
        )
    else:
        text_color_identifier = resolved.text_color
    if text_color_identifier not in configuration.palette:
        source = "explicit" if overrides.text_color is not None else "published"
        raise DailyImagePreparationError(
            f"{source} text color {text_color_identifier!r} is unavailable in the configured palette"
        )
    text_color = _palette_color(configuration, text_color_identifier)

    if overrides.tint is not None:
        decoration_color_identifier = _strict_pool_override(
            overrides.tint,
            configuration.decoration_color_pools,
            configuration.palette,
            "decoration tint color",
            chooser,
        )
        if decoration_color_identifier not in configuration.palette:
            raise DailyImagePreparationError(
                f"explicit decoration tint color {decoration_color_identifier!r} is not in the palette"
            )
    else:
        decoration_color_identifier = resolved.decoration_color
        tintable = decoration is not None and any(
            _decoration_layer_is_tintable(decoration, layer) for layer in decoration.layers
        )
        if (
            tintable
            and decoration_color_identifier is not None
            and decoration_color_identifier not in configuration.palette
        ):
            raise DailyImagePreparationError(
                f"published decoration tint color {decoration_color_identifier!r} is unavailable in the "
                "configured palette"
            )
    tintable = decoration is not None and any(decoration.tintable and layer.tintable for layer in decoration.layers)
    if tintable and decoration_color_identifier is None and overrides.decoration is not None:
        raise DailyImagePreparationError("explicit tint is required for a tintable decoration")
    decoration_tint = (
        _palette_color(configuration, decoration_color_identifier)
        if tintable and decoration_color_identifier is not None
        else None
    )

    faces = dict(resolved.font_faces)
    faces.update(overrides.font_faces)
    font_overrides = PresentationOverrides(
        font=overrides.font if overrides.font is not None else resolved.font_bundle,
        font_faces=faces,
    )
    fonts = _resolve_fonts(snapshot, configuration, decoration, chooser, font_overrides)
    style = resolved.presentation_style if overrides.style is None else overrides.style
    if style not in {"centered", "left-aligned"}:
        raise DailyImagePreparationError(f"unsupported presentation style: {style!r}")
    qr_enabled = resolved.qr_enabled if overrides.qr_enabled is None else overrides.qr_enabled
    if type(qr_enabled) is not bool:
        raise DailyImagePreparationError("resolved QR policy must be a boolean")
    return _PresentationChoices(
        decoration_identifier,
        decoration,
        background_identifier,
        strict_background,
        decoration is not None,
        text_color,
        text_color_identifier,
        decoration_tint,
        decoration_color_identifier if tintable else None,
        MappingProxyType(fonts),
        style,
        qr_enabled,
        overrides.qr_enabled is not None,
    )


def _resolve_presentation(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    decoration: DecorationResource | None,
    output_specification: ResolvedOutputSpecification,
    presentation_style: str,
    overrides: PresentationOverrides,
    resolved_presentation: ResolvedPresentation | None = None,
) -> tuple[LiteraryComposition, PresentationGeometry, int, int, str]:
    composition = LiteraryComposition(
        quotation=snapshot.quotation_text,
        source=snapshot.source,
        attribution=snapshot.attribution,
    )
    insets = (
        resolved_presentation.insets
        if resolved_presentation is not None
        else (
            configuration.presentation_insets
            if decoration is None or decoration.presentation_insets is None
            else decoration.presentation_insets
        )
    )
    try:
        geometry = resolve_presentation_geometry(output_specification, insets)
    except PresentationGeometryError as error:
        raise DailyImagePreparationError(f"cannot resolve literary presentation geometry: {error}") from error
    min_font_size = (
        configuration.min_font_size if resolved_presentation is None else resolved_presentation.min_font_size
    )
    max_font_size = (
        configuration.max_font_size if resolved_presentation is None else resolved_presentation.max_font_size
    )
    min_design_font_size = min_font_size if overrides.min_font_size is None else overrides.min_font_size
    max_design_font_size = max_font_size if overrides.max_font_size is None else overrides.max_font_size
    for field_name, font_size in (
        ("min_font_size", min_design_font_size),
        ("max_font_size", max_design_font_size),
    ):
        if isinstance(font_size, bool) or not isinstance(font_size, int) or font_size <= 0:
            raise DailyImagePreparationError(f"{field_name} override must be a positive integer")
    if min_design_font_size > max_design_font_size:
        raise DailyImagePreparationError(
            "invalid effective font-size range: "
            f"minimum {min_design_font_size} exceeds maximum {max_design_font_size}; "
            "adjust the viewer overrides or configured bounds so the minimum is less than or equal to the maximum"
        )
    design_width = geometry.design_canvas_size[0]
    presentation_width = geometry.presentation_canvas_size[0]
    return (
        composition,
        geometry,
        max(1, round_half_up(min_design_font_size * presentation_width, design_width)),
        max(1, round_half_up(max_design_font_size * presentation_width, design_width)),
        presentation_style,
    )


def _palette_color(configuration: ApplicationConfiguration, identifier: str) -> tuple[int, int, int]:
    value = configuration.palette[identifier]
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _preference_candidates(
    preference: str | Sequence[str] | None,
    pools: Mapping[str, tuple[str, ...]],
    source: str,
) -> tuple[str, ...]:
    if preference is None:
        return ()
    members = (preference,) if isinstance(preference, str) else preference
    result: list[str] = []
    seen: set[str] = set()
    for member in members:
        if not isinstance(member, str):
            _LOGGER.warning("Invalid resource preference from %s; excluding it", source)
            continue
        if member.startswith("@"):
            name = member[1:]
            if not valid_identifier(name):
                _LOGGER.warning("Pool reference %r from %s is malformed; excluding it", member, source)
                continue
            candidates = pools.get(name)
            if candidates is None:
                _LOGGER.warning("Pool reference %r from %s is unknown; excluding it", member, source)
                continue
        else:
            candidates = (member,)
        for identifier in candidates:
            if identifier not in seen:
                seen.add(identifier)
                result.append(identifier)
    return tuple(result)


def _strict_pool_override(
    value: str,
    pools: Mapping[str, tuple[str, ...]],
    available: Mapping[str, object],
    label: str,
    chooser: random.Random,
) -> str:
    if not value.startswith("@"):
        return value
    candidates = _preference_candidates(value, pools, f"explicit {label}")
    usable = tuple(identifier for identifier in candidates if identifier in available)
    if not usable:
        raise DailyImagePreparationError(f"explicit {label} pool reference {value!r} has no selectable candidates")
    return chooser.choice(usable)


def _resolve_palette_preference(
    configuration: ApplicationConfiguration,
    levels: Sequence[tuple[str, Sequence[str] | None, Mapping[str, tuple[str, ...]]]],
    chooser: random.Random,
) -> tuple[str, tuple[int, int, int]]:
    for source, candidates, pools in levels:
        if candidates is None:
            continue
        resolved = _preference_candidates(candidates, pools, source)
        usable = tuple(identifier for identifier in resolved if identifier in configuration.palette)
        for identifier in resolved:
            if identifier not in configuration.palette:
                _LOGGER.warning("Palette identifier %r from %s is unavailable; excluding it", identifier, source)
        if usable:
            identifier = chooser.choice(usable)
            return identifier, _palette_color(configuration, identifier)
    return "black", _palette_color(configuration, "black")


def _resolve_text_color(
    configuration: ApplicationConfiguration,
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    decoration: DecorationResource | None,
    background: BackgroundResource | None,
    chooser: random.Random,
    override: str | None = None,
    destination_preference: tuple[str, ...] | None = None,
    *,
    on_resolved_identifier: Callable[[str], None] | None = None,
) -> tuple[int, int, int]:
    if override is not None:
        identifier = _strict_pool_override(
            override,
            configuration.text_color_pools,
            configuration.palette,
            "text color",
            chooser,
        )
        if identifier not in configuration.palette:
            raise DailyImagePreparationError(f"explicit text color {identifier!r} is not in the palette")
        if on_resolved_identifier is not None:
            on_resolved_identifier(identifier)
        return _palette_color(configuration, identifier)
    identifier, color = _resolve_palette_preference(
        configuration,
        (
            ("destination presentation", destination_preference, configuration.text_color_pools),
            ("content entry text_color", snapshot.text_color, configuration.text_color_pools),
            (
                "selected background",
                None if background is None else background.text_color,
                configuration.text_color_pools,
            ),
            (
                "selected decoration",
                None if decoration is None else decoration.text_color,
                configuration.text_color_pools,
            ),
            ("text.colors.pools", configuration.default_text_colors, configuration.text_color_pools),
        ),
        chooser,
    )
    _LOGGER.debug("Resolved literary text color %s", identifier)
    if on_resolved_identifier is not None:
        on_resolved_identifier(identifier)
    return color


def _resolve_decoration_tint(
    configuration: ApplicationConfiguration,
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    decoration: DecorationResource | None,
    chooser: random.Random,
    layers: Sequence[DecorationLayerResource],
    forced_tint: tuple[int, int, int] | None = None,
    background: BackgroundResource | None = None,
    destination_preference: tuple[str, ...] | None = None,
    *,
    on_resolved_identifier: Callable[[str], None] | None = None,
) -> tuple[int, int, int] | None:
    if decoration is None or not any(decoration.tintable and layer.tintable for layer in layers):
        return None
    if forced_tint is not None:
        return forced_tint

    identifier, color = _resolve_palette_preference(
        configuration,
        (
            ("destination presentation", destination_preference, configuration.decoration_color_pools),
            ("content entry decoration_color", snapshot.decoration_color, configuration.decoration_color_pools),
            (
                "selected background",
                None if background is None else background.decoration_color,
                configuration.decoration_color_pools,
            ),
            ("selected decoration", decoration.decoration_color, configuration.decoration_color_pools),
            (
                "decorations.colors.pools",
                configuration.default_decoration_colors,
                configuration.decoration_color_pools,
            ),
        ),
        chooser,
    )
    _LOGGER.debug("Resolved decoration color %s", identifier)
    if on_resolved_identifier is not None:
        on_resolved_identifier(identifier)
    return color


def _generate_daily_background(
    design_canvas_size: tuple[int, int],
    identifier: str,
    registry: Mapping[str, BackgroundResource],
    *,
    strict: bool = False,
    on_fallback: Callable[[], None] | None = None,
) -> Image.Image:
    base = Image.new("RGB", design_canvas_size, _BACKGROUND_COLOR)
    if identifier == "none":
        return base
    resource = registry.get(identifier)
    if resource is None:
        if strict:
            raise DailyImagePreparationError(f"explicit background {identifier!r} is unavailable")
        _LOGGER.warning("Committed background %r is unavailable; using the paper-white base", identifier)
        if on_fallback is not None:
            on_fallback()
        return base
    try:
        if resource.layers:
            for index, layer in enumerate(resource.layers, start=1):
                try:
                    with load_composition_layer_image(layer) as image:
                        _compose_layer(base, image, layer)
                except Exception as error:
                    raise ValueError(f"layer {index} ({layer.image}) is unavailable or unusable: {error}") from error
        elif resource.path is not None:
            with load_background_image(resource) as image:
                _compose_layer(base, image, CompositionLayerResource(resource.path, "cover"))
        else:
            raise ValueError("background has neither a standalone image nor any layers")
    except Exception as error:
        if strict:
            base.close()
            raise DailyImagePreparationError(
                f"explicit background {identifier!r} is unavailable or unusable: {error}"
            ) from error
        base.close()
        _LOGGER.warning(
            "Committed background %r is unavailable or unusable; using the paper-white base: %s",
            identifier,
            error,
        )
        if on_fallback is not None:
            on_fallback()
        return Image.new("RGB", design_canvas_size, _BACKGROUND_COLOR)
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
    on_fallback: Callable[[], None] | None = None,
) -> Image.Image:
    if identifier == "none":
        return background
    resource = registry.get(identifier)
    if resource is None:
        if strict:
            raise DailyImagePreparationError(f"decoration {identifier!r} is unavailable")
        _LOGGER.warning("Committed decoration %r is unavailable; discarding the decoration", identifier)
        if on_fallback is not None:
            on_fallback()
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
                    bounds = _compose_layer(background, source, layer)
                    if bounds is not None and on_nine_slice_guide is not None:
                        on_nine_slice_guide(layer, *bounds)
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
            _LOGGER.warning("%s; discarding the decoration", message)
            if on_fallback is not None:
                on_fallback()
            return background
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


def _paste_layer_region(background: Image.Image, region: Image.Image, position: tuple[int, int]) -> None:
    if region.mode == "RGBA":
        background.paste(region, position, region)
    else:
        background.paste(region, position)


def _compose_layer(
    background: Image.Image,
    source: Image.Image,
    layer: CompositionLayerResource,
) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    if layer.method == "contain":
        contained = ImageOps.contain(source, background.size, method=Image.Resampling.LANCZOS)
        try:
            position = (
                (background.width - contained.width) // 2,
                (background.height - contained.height) // 2,
            )
            _paste_layer_region(background, contained, position)
        finally:
            contained.close()
        return None
    if layer.method == "cover":
        _compose_cover(background, source)
        return None
    if layer.method == "anchor":
        _compose_anchor(background, source, layer)
        return None
    return _compose_nine_slice(background, source, layer)


def _compose_anchor(background: Image.Image, source: Image.Image, layer: CompositionLayerResource) -> None:
    if layer.scale not in {"horizontal", "vertical", "none"} or layer.anchor is None:
        raise ValueError("anchor parameters are missing or invalid")

    if layer.scale == "horizontal":
        scale = Fraction(background.width, source.width)
        size = (background.width, max(1, _rounded_fraction(source.height * scale)))
    elif layer.scale == "vertical":
        scale = Fraction(background.height, source.height)
        size = (max(1, _rounded_fraction(source.width * scale)), background.height)
    else:
        size = source.size

    scaled = source if size == source.size else source.resize(size, Image.Resampling.LANCZOS)
    horizontal_position = {
        "left": 0,
        "center": (background.width - scaled.width) // 2,
        "right": background.width - scaled.width,
    }.get(layer.anchor.horizontal)
    vertical_position = {
        "top": 0,
        "center": (background.height - scaled.height) // 2,
        "bottom": background.height - scaled.height,
    }.get(layer.anchor.vertical)
    try:
        if horizontal_position is None or vertical_position is None:
            raise ValueError("anchor position is invalid")
        _paste_layer_region(background, scaled, (horizontal_position, vertical_position))
    finally:
        if scaled is not source:
            scaled.close()


def _rounded_fraction(value: Fraction) -> int:
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _compose_cover(background: Image.Image, source: Image.Image) -> None:
    if source.size == background.size:
        _paste_layer_region(background, source, (0, 0))
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
                _paste_layer_region(background, covered, (0, 0))
            finally:
                covered.close()
        else:
            _paste_layer_region(background, scaled, (0, 0))
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
    layer: CompositionLayerResource,
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
            _paste_layer_region(background, transformed, (dest_x, dest_y))
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
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    decoration: DecorationResource | None,
    chooser: random.Random,
    overrides: PresentationOverrides,
    destination_presentation: DestinationPresentation = DestinationPresentation(),
    *,
    recovery_only: bool = False,
) -> dict[str, ResolvedFont]:
    preferences: list[tuple[str, str]] = []
    if destination_presentation.font is not None:
        preferences.append(("destination presentation", destination_presentation.font))
    if snapshot.font is not None:
        preferences.append(("content entry", snapshot.font))
    if not recovery_only and decoration is not None and decoration.font is not None:
        preferences.append(("selected decoration", decoration.font))

    resolved_bundle: FontResource | None = None
    regular: ResolvedFont | None = None
    tried: set[str] = set()
    if overrides.font is not None:
        if overrides.font.startswith("@"):
            candidates = list(_preference_candidates(overrides.font, configuration.font_pools, "explicit font"))
            candidates = [identifier for identifier in candidates if identifier in configuration.fonts]
            while candidates:
                identifier = chooser.choice(candidates)
                candidates.remove(identifier)
                resource = configuration.fonts[identifier]
                try:
                    regular = _read_font(resource)
                    resolved_bundle = resource
                    break
                except Exception as error:
                    _LOGGER.warning("Explicit font %r in pool %r is unusable: %s", identifier, overrides.font, error)
            if resolved_bundle is None:
                raise DailyImagePreparationError(
                    f"explicit font pool reference {overrides.font!r} has no selectable candidates"
                )
        else:
            resource = configuration.fonts.get(overrides.font)
            if resource is None:
                raise DailyImagePreparationError(f"explicit font {overrides.font!r} is not registered")
            try:
                regular = _read_font(resource)
            except Exception as error:
                raise DailyImagePreparationError(f"explicit font {overrides.font!r} is unusable: {error}") from error
            resolved_bundle = resource
    if overrides.font is None:
        for source, preference in preferences:
            pool = list(_preference_candidates(preference, configuration.font_pools, source))
            while pool:
                identifier = chooser.choice(pool)
                pool.remove(identifier)
                tried.add(identifier)
                resource = configuration.fonts.get(identifier)
                if resource is None:
                    _LOGGER.warning(
                        "Requested font %r from %s is unavailable; checking the next candidate or preference",
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
                        "Requested font %r from %s is unusable; checking the next candidate or preference: %s",
                        identifier,
                        source,
                        error,
                    )
            if resolved_bundle is not None:
                break

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
        try:
            path = files("refrain").joinpath("assets", "fonts", "source-sans-3", "SourceSans3-Regular.ttf")
            registered = configuration.fonts.get("source-sans-3")
            if registered is not None and registered.bundled:
                resolved_bundle = FontResource(
                    "source-sans-3",
                    path,
                    bundled=True,
                    faces={**registered.faces, "regular": path},
                    font_faces=registered.font_faces,
                )
            else:
                resolved_bundle = FontResource("source-sans-3", path, bundled=True)
            regular = _read_font(resolved_bundle)
        except Exception as error:
            raise DailyImagePreparationError(
                "cannot resolve a usable font: packaged emergency font source-sans-3/regular is missing or "
                f"unusable; repair or reinstall the Refrain package: {error}"
            ) from error
        _LOGGER.warning("No configured font is usable; using packaged emergency font source-sans-3/regular")

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
                resolved[role] = regular
                continue
        resolved[role] = loaded_faces[face]
    return resolved


def _resolve_decoration(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
    override: str | None = None,
    destination_preference: str | None = None,
) -> tuple[str, DecorationResource | None]:
    if override is not None:
        identifier = _strict_pool_override(
            override,
            configuration.decoration_pools,
            {**configuration.decorations, "none": None},
            "decoration",
            chooser,
        )
        if identifier == "none":
            return "none", None
        resource = configuration.decorations.get(identifier)
        if resource is None:
            raise DailyImagePreparationError(f"explicit decoration {identifier!r} is not registered")
        return identifier, resource
    for source, preferred in (
        ("destination presentation", destination_preference),
        ("content entry", snapshot.decoration),
    ):
        if preferred is None:
            continue
        if preferred == "none":
            return "none", None
        candidates = _preference_candidates(preferred, configuration.decoration_pools, source)
        usable = tuple(
            identifier for identifier in candidates if identifier == "none" or identifier in configuration.decorations
        )
        if usable:
            identifier = chooser.choice(usable)
            return identifier, configuration.decorations.get(identifier)
        if source == "content entry":
            _LOGGER.warning("Requested decoration %r is unavailable; using the default decoration pool", preferred)
        else:
            _LOGGER.warning(
                "Requested decoration %r from %s is unavailable; checking the next preference", preferred, source
            )
    candidates = tuple(
        identifier
        for identifier in configuration.default_decorations
        if identifier == "none" or identifier in configuration.decorations
    )
    if not candidates:
        return "none", None
    identifier = chooser.choice(candidates)
    return identifier, configuration.decorations.get(identifier)


def _resolve_background(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    decoration: DecorationResource | None,
    configuration: ApplicationConfiguration,
    chooser: random.Random,
    override: str | None = None,
    destination_preference: str | None = None,
) -> str:
    if override is not None:
        identifier = _strict_pool_override(
            override,
            configuration.background_pools,
            {**configuration.backgrounds, "none": None},
            "background",
            chooser,
        )
        if identifier == "none":
            return "none"
        if identifier not in configuration.backgrounds:
            raise DailyImagePreparationError(f"explicit background {identifier!r} is not registered")
        return identifier
    preferences = (
        ("destination presentation", destination_preference),
        ("content entry", snapshot.background),
        ("selected decoration", None if decoration is None else decoration.background),
    )
    for source, preferred in preferences:
        if preferred is None:
            continue
        candidates = _preference_candidates(preferred, configuration.background_pools, source)
        usable = tuple(
            identifier for identifier in candidates if identifier == "none" or identifier in configuration.backgrounds
        )
        if usable:
            return chooser.choice(usable)
        _LOGGER.warning(
            "Requested background %r from %s is unavailable; checking the next preference",
            preferred,
            source,
        )
    candidates = tuple(
        identifier
        for identifier in configuration.default_backgrounds
        if identifier == "none" or identifier in configuration.backgrounds
    )
    return chooser.choice(candidates) if candidates else "none"


def _prepare_daily_images_for_specification(
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    output_specification: ResolvedOutputSpecification,
    choices: _PresentationChoices,
    overrides: PresentationOverrides,
    variant_key: ResolvedOutputSpecification | PreparedImageVariantKey,
    *,
    resolved_presentation: ResolvedPresentation | None = None,
    selection_revision: int | None = None,
    on_metadata: (
        Callable[[ResolvedOutputSpecification | PreparedImageVariantKey, tuple[dict[str, object], ...]], None] | None
    ) = None,
    strict_decoration: bool = False,
    on_resolved_bounds: (
        Callable[[ResolvedOutputSpecification | PreparedImageVariantKey, PixelBounds], None] | None
    ) = None,
    qr_disabled_reason: str | None = None,
    qr_declaration: Mapping[str, object] | None = None,
    on_diagnostics: Callable[[ResolvedOutputSpecification, PreparationDiagnostics], None] | None = None,
    on_presentation_image: (
        Callable[[ResolvedOutputSpecification, Image.Image, PreparationDiagnostics], None] | None
    ) = None,
) -> tuple[Image.Image, ...]:
    """Prepare complete, independent images for explicit cumulative reveal stages.

    Semantic preferences from ``snapshot`` are resolved against current configuration
    and resources once for the complete stage set. Stages are never inferred from the clock.
    """
    if not isinstance(snapshot, (DailySnapshot, _UncommittedLiteraryContent)):
        raise DailyImagePreparationError("snapshot must be a DailySnapshot")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if not isinstance(configuration, ApplicationConfiguration):
        raise DailyImagePreparationError("configuration must be a validated ApplicationConfiguration")
    if not isinstance(output_specification, ResolvedOutputSpecification):
        raise DailyImagePreparationError("output_specification must be a ResolvedOutputSpecification")
    decoration_identifier = choices.decoration_identifier
    decoration = choices.decoration
    geometry = resolve_presentation_geometry(output_specification, PresentationInsets(0, 0, 0, 0))
    presentation_canvas_size = geometry.presentation_canvas_size

    def resolve_effective_qr(
        effective_decoration: DecorationResource | None,
    ) -> tuple[QRCodePlacement | None, str | None]:
        if qr_declaration is None:
            return None, "no QR payload for this audience"
        if not choices.qr_enabled:
            return None, qr_disabled_reason or (
                "QR generation is disabled by viewer override"
                if choices.qr_policy_overridden
                else "QR generation is disabled by configuration"
            )
        if effective_decoration is not None and not effective_decoration.qr_ready:
            return None, f"decoration {effective_decoration.identifier!r} is not marked qr_ready"
        try:
            return (
                resolve_qr_placement(
                    output_specification,
                    None if effective_decoration is None else effective_decoration.qr_positioning,
                ),
                None,
            )
        except QRCodePlacementError as error:
            _LOGGER.warning("QR generation is disabled for this preparation: %s", error)
            return None, str(error)

    qr_placement, qr_unavailable_reason = resolve_effective_qr(decoration)
    decoration_layers = _eligible_decoration_layers(decoration, qr_placement is not None)
    text_color = choices.text_color
    qr_parameters = replace(PRODUCTION_QR_PARAMETERS, url=None if qr_declaration is None else qr_declaration["payload"])
    decoration_tint = choices.decoration_tint
    nine_slice_guides: list[NineSliceGuide] = []
    effective_background_identifier = choices.background_identifier
    decoration_failed = False

    def remember_background_fallback() -> None:
        nonlocal effective_background_identifier
        effective_background_identifier = "none"

    def remember_decoration_fallback() -> None:
        nonlocal decoration_failed
        decoration_failed = True

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
            else _generate_daily_background(*background_arguments, on_fallback=remember_background_fallback)
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
                on_fallback=remember_decoration_fallback,
            )
            if decoration_failed:
                background.close()
                background = _generate_daily_background(
                    geometry.design_canvas_size,
                    effective_background_identifier,
                    configuration.backgrounds,
                    strict=choices.strict_background,
                    on_fallback=remember_background_fallback,
                )
                decoration_identifier, decoration = "none", None
                decoration_layers = ()
                nine_slice_guides.clear()
                qr_placement, qr_unavailable_reason = resolve_effective_qr(None)
                if resolved_presentation is not None:
                    resolved_presentation = replace(resolved_presentation, insets=configuration.presentation_insets)
            composition, geometry, min_font_size, max_font_size, style = _resolve_presentation(
                snapshot,
                configuration,
                decoration,
                output_specification,
                choices.presentation_style,
                overrides,
                resolved_presentation,
            )
            if on_resolved_bounds is not None:
                on_resolved_bounds(variant_key, geometry.presentation_literary_bounds)
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
                if on_metadata is not None:
                    if selection_revision is None:
                        raise DailyImagePreparationError("selection_revision is required when capturing metadata")
                    if (
                        decoration is not None
                        and choices.decoration_tint is not None
                        and choices.decoration_color_identifier is None
                    ):
                        raise DailyImagePreparationError(
                            "cannot capture publication metadata for an RGB tint without a palette identifier"
                        )
                    actual_insets = (
                        resolved_presentation.insets
                        if resolved_presentation is not None
                        else (
                            configuration.presentation_insets
                            if decoration is None or decoration.presentation_insets is None
                            else decoration.presentation_insets
                        )
                    )
                    font_faces = {
                        role: (resolved.identifier.split(":", 1)[1] if ":" in resolved.identifier else "regular")
                        for role, resolved in fonts.items()
                    }
                    effective_presentation = {
                        "style": style,
                        "background": effective_background_identifier,
                        "decoration": decoration_identifier,
                        "fonts": {
                            "bundle": fonts["quotation"].identifier.split(":", 1)[0],
                            "faces": font_faces,
                        },
                        "colors": {
                            "text": choices.text_color_identifier,
                            "decoration": (
                                choices.decoration_color_identifier
                                if decoration is not None
                                and any(_decoration_layer_is_tintable(decoration, layer) for layer in decoration_layers)
                                else None
                            ),
                        },
                        "font_size_range": {
                            "minimum": (
                                (
                                    configuration.min_font_size
                                    if resolved_presentation is None
                                    else resolved_presentation.min_font_size
                                )
                                if overrides.min_font_size is None
                                else overrides.min_font_size
                            ),
                            "maximum": (
                                (
                                    configuration.max_font_size
                                    if resolved_presentation is None
                                    else resolved_presentation.max_font_size
                                )
                                if overrides.max_font_size is None
                                else overrides.max_font_size
                            ),
                        },
                        "insets": {
                            "left": actual_insets.left,
                            "right": actual_insets.right,
                            "top": actual_insets.top,
                            "bottom": actual_insets.bottom,
                        },
                    }
                    metadata = tuple(
                        {
                            "selection_revision": selection_revision,
                            "visibility": {
                                "quotation": stage.quotation,
                                "source": stage.source,
                                "attribution": stage.attribution,
                            },
                            "effective_presentation": effective_presentation,
                            "rendered_qr": (
                                {"payload": qr_declaration["payload"], "visibility": list(qr_declaration["visibility"])}
                                if qr_placement is not None and qr_declaration is not None
                                else None
                            ),
                            "output_specification": {
                                "aspect_ratio": output_specification.aspect_ratio,
                                "requested_output_size": list(output_specification.requested_output_size),
                            },
                        }
                        for stage in stages
                    )
                    on_metadata(variant_key, metadata)
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
    snapshot: DailySnapshot | _UncommittedLiteraryContent,
    stages: Sequence[CompositionVisibility],
    configuration: ApplicationConfiguration,
    output_specifications: Sequence[ResolvedOutputSpecification | PreparedImageVariantKey],
    *,
    chooser: random.Random | None = None,
    selection_revision: int | None = None,
    on_metadata: (
        Callable[[ResolvedOutputSpecification | PreparedImageVariantKey, tuple[dict[str, object], ...]], None] | None
    ) = None,
    strict_decoration: bool = False,
    on_resolved_bounds: (
        Callable[[ResolvedOutputSpecification | PreparedImageVariantKey, PixelBounds], None] | None
    ) = None,
    force_white_background: bool = False,
    forced_decoration_tint: tuple[int, int, int] | None = None,
    overrides: PresentationOverrides | None = None,
    resolved_presentation: ResolvedPresentation | None = None,
    canonical_presentation: Mapping[str, object] | None = None,
    qr_declaration: Mapping[str, object] | None = None,
    strict_published_presentation: bool = False,
    qr_disabled_reason: str | None = None,
    on_diagnostics: Callable[[ResolvedOutputSpecification, PreparationDiagnostics], None] | None = None,
    on_presentation_image: (
        Callable[[ResolvedOutputSpecification, Image.Image, PreparationDiagnostics], None] | None
    ) = None,
) -> Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, tuple[Image.Image, ...]]:
    """Prepare complete reveal-stage image variants for all required destination groups."""
    if not isinstance(snapshot, (DailySnapshot, _UncommittedLiteraryContent)):
        raise DailyImagePreparationError("snapshot must be a DailySnapshot")
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)) or not stages:
        raise DailyImagePreparationError("stages must be a nonempty sequence of CompositionVisibility values")
    if not isinstance(configuration, ApplicationConfiguration):
        raise DailyImagePreparationError("configuration must be a validated ApplicationConfiguration")
    if resolved_presentation is not None and not isinstance(resolved_presentation, ResolvedPresentation):
        raise DailyImagePreparationError("resolved_presentation must be ResolvedPresentation")
    if canonical_presentation is not None:
        if resolved_presentation is not None:
            raise DailyImagePreparationError("provide only one resolved presentation")
        resolved_presentation = _resolved_from_document(canonical_presentation)
    if qr_declaration is not None:
        from .content import validate_qr_payload

        try:
            if set(qr_declaration) != {"payload", "visibility"} or qr_declaration["visibility"] not in (
                ["external"],
                ["internal"],
            ):
                raise ValueError("QR declaration must identify exactly one audience")
            if validate_qr_payload(qr_declaration["payload"]) is None:
                raise ValueError("QR declaration requires a payload")
        except (TypeError, ValueError, KeyError) as error:
            raise DailyImagePreparationError(f"invalid QR declaration: {error}") from error
    if on_metadata is not None and (type(selection_revision) is not int or selection_revision <= 0):
        raise DailyImagePreparationError("metadata capture requires a positive selection_revision")
    if not isinstance(output_specifications, Sequence) or isinstance(output_specifications, (str, bytes)):
        raise DailyImagePreparationError("output_specifications must be a nonempty sequence")
    if not output_specifications or any(
        not isinstance(specification, (ResolvedOutputSpecification, PreparedImageVariantKey))
        for specification in output_specifications
    ):
        raise DailyImagePreparationError("output_specifications must contain resolved specifications or variant keys")
    group_specifications: dict[DestinationPresentation, set[ResolvedOutputSpecification | PreparedImageVariantKey]] = {}
    for key in output_specifications:
        if isinstance(key, PreparedImageVariantKey):
            if key.presentation.is_empty and key.qr_payload is None:
                raise DailyImagePreparationError("prepared variant keys must have nonempty presentation requirements")
            expected_payload = (
                None if key.presentation.qr_enabled is False or qr_declaration is None else qr_declaration["payload"]
            )
            if key.qr_payload != expected_payload:
                raise DailyImagePreparationError("variant QR payload does not match the selected QR declaration")
            group_specifications.setdefault(key.presentation, set()).add(key)
        else:
            group_specifications.setdefault(DestinationPresentation(), set()).add(key)
    results: dict[ResolvedOutputSpecification | PreparedImageVariantKey, tuple[Image.Image, ...]] = {}
    chooser = chooser if chooser is not None else random.Random()
    effective_overrides = PresentationOverrides() if overrides is None else overrides
    try:
        for destination_presentation, specifications in group_specifications.items():
            group_presentation = resolved_presentation
            if canonical_presentation is not None and not strict_published_presentation:
                choices, group_presentation = _resolve_effective_choices(
                    snapshot,
                    configuration,
                    chooser,
                    resolved_presentation,
                    destination_presentation,
                    effective_overrides,
                )
            else:
                choices = _resolve_presentation_choices(
                    snapshot,
                    configuration,
                    chooser,
                    force_white_background=force_white_background,
                    forced_decoration_tint=forced_decoration_tint,
                    overrides=effective_overrides,
                    resolved_presentation=resolved_presentation,
                    destination_presentation=destination_presentation,
                )
                if (
                    strict_published_presentation
                    and group_presentation is not None
                    and effective_overrides.decoration is not None
                ):
                    insets = (
                        configuration.presentation_insets
                        if choices.decoration is None or choices.decoration.presentation_insets is None
                        else choices.decoration.presentation_insets
                    )
                    group_presentation = replace(group_presentation, insets=insets)
            for variant_key in sorted(
                specifications,
                key=lambda key: (
                    (key.output_specification if isinstance(key, PreparedImageVariantKey) else key).aspect_ratio,
                    (
                        key.output_specification if isinstance(key, PreparedImageVariantKey) else key
                    ).requested_output_size,
                ),
            ):
                output_specification = (
                    variant_key.output_specification
                    if isinstance(variant_key, PreparedImageVariantKey)
                    else variant_key
                )
                results[variant_key] = _prepare_daily_images_for_specification(
                    snapshot,
                    stages,
                    configuration,
                    output_specification,
                    choices,
                    effective_overrides,
                    variant_key,
                    resolved_presentation=group_presentation,
                    selection_revision=selection_revision,
                    on_metadata=on_metadata,
                    strict_decoration=strict_decoration,
                    on_resolved_bounds=on_resolved_bounds,
                    qr_disabled_reason=qr_disabled_reason,
                    qr_declaration=qr_declaration,
                    on_diagnostics=on_diagnostics,
                    on_presentation_image=on_presentation_image,
                )
    except Exception:
        for images in results.values():
            for image in images:
                image.close()
        raise
    return MappingProxyType(results)


def _prepare_uncommitted_literary_images(
    composition: LiteraryComposition,
    configuration: ApplicationConfiguration,
    output_specifications: Sequence[ResolvedOutputSpecification | PreparedImageVariantKey],
    *,
    on_variant_error: (
        Callable[[ResolvedOutputSpecification | PreparedImageVariantKey, DailyImagePreparationError], None] | None
    ) = None,
    canonical_cache: dict[str, object] | None = None,
) -> Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, tuple[Image.Image, ...]]:
    content = _UncommittedLiteraryContent(composition.quotation, composition.source, composition.attribution)
    chooser = random.Random()
    if canonical_cache is not None and canonical_cache:
        canonical = canonical_cache
    else:
        canonical = resolve_canonical_presentation(content, configuration, chooser=chooser)
        if canonical_cache is not None:
            canonical_cache.update(canonical)
    stages = (
        CompositionVisibility(
            quotation=True,
            source=composition.source is not None,
            attribution=composition.attribution is not None,
        ),
    )
    if on_variant_error is None:
        return prepare_daily_images(
            content, stages, configuration, output_specifications, chooser=chooser, canonical_presentation=canonical
        )
    if not output_specifications:
        raise DailyImagePreparationError("output_specifications must be a nonempty sequence")
    results = {}
    try:
        for key in dict.fromkeys(output_specifications):
            try:
                results.update(
                    prepare_daily_images(
                        content, stages, configuration, (key,), chooser=chooser, canonical_presentation=canonical
                    )
                )
            except DailyImagePreparationError as error:
                on_variant_error(key, error)
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
    "ResolvedPresentation",
    "resolve_canonical_presentation",
    "prepare_daily_images",
]

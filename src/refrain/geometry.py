"""Resolved presentation geometry independent of rendering and display hardware."""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from types import MappingProxyType
from typing import Mapping

REFERENCE_SIZE = (3840, 2400)
DEFAULT_OUTPUT_SIZE = (1920, 1080)
DEFAULT_PRESENTATION_INSETS = (384, 384, 324, 324)
_LEGACY_ASPECT_RATIOS = frozenset(("4:3", "16:9", "16:10"))

PixelBounds = tuple[int, int, int, int]


class PresentationGeometryError(ValueError):
    """Raised when output dimensions or literary geometry are invalid."""


@dataclass(frozen=True)
class PresentationAspect:
    """Canonical geometry for one supported presentation aspect ratio."""

    width: int
    height: int
    working_size: tuple[int, int]
    crop_origin: tuple[int, int]

    @property
    def reduced_ratio(self) -> tuple[int, int]:
        """Return primitive integer components for the native-raster lattice."""
        divisor = gcd(self.width, self.height)
        return self.width // divisor, self.height // divisor


SUPPORTED_PRESENTATION_ASPECTS: Mapping[str, PresentationAspect] = MappingProxyType(
    {
        "4:3": PresentationAspect(4, 3, (3200, 2400), (320, 0)),
        "5:3": PresentationAspect(5, 3, (3840, 2304), (0, 48)),
        "16:9": PresentationAspect(16, 9, (3840, 2160), (0, 120)),
        "16:10": PresentationAspect(16, 10, (3840, 2400), (0, 0)),
    }
)


@dataclass(frozen=True)
class ResolvedOutputSpecification:
    """Declared presentation aspect and requested raster, resolved for native rendering."""

    aspect_ratio: str
    requested_size: tuple[int, int]

    def __post_init__(self) -> None:
        if not isinstance(self.aspect_ratio, str) or self.aspect_ratio not in SUPPORTED_PRESENTATION_ASPECTS:
            raise PresentationGeometryError(f"unsupported presentation aspect ratio: {self.aspect_ratio!r}")
        object.__setattr__(self, "requested_size", validate_requested_size(self.requested_size))

    @property
    def native_render_size(self) -> tuple[int, int]:
        """Return the nearest positive integer raster at the declared aspect ratio."""
        aspect = SUPPORTED_PRESENTATION_ASPECTS[self.aspect_ratio]
        width, height = self.requested_size
        if width * aspect.height == height * aspect.width:
            return self.requested_size

        ratio_width, ratio_height = aspect.reduced_ratio
        projected_scale = round_half_up(
            ratio_width * width + ratio_height * height,
            ratio_width * ratio_width + ratio_height * ratio_height,
        )
        scale = max(1, projected_scale)
        return ratio_width * scale, ratio_height * scale

    @property
    def requires_resampling(self) -> bool:
        return self.native_render_size != self.requested_size


@dataclass(frozen=True)
class PresentationInsets:
    """Independent working-canvas pixel distances from each edge."""

    left: int
    right: int
    top: int
    bottom: int


@dataclass(frozen=True)
class PresentationGeometry:
    """Reference, working, requested, native-render, and literary dimensions."""

    reference_size: tuple[int, int]
    working_size: tuple[int, int]
    crop_origin: tuple[int, int]
    output_size: tuple[int, int]
    working_region: PixelBounds
    output_region: PixelBounds
    aspect_ratio: str
    native_render_size: tuple[int, int]

    @property
    def requested_size(self) -> tuple[int, int]:
        """Return the exact raster requested by the output specification."""
        return self.output_size

    @property
    def native_render_region(self) -> PixelBounds:
        """Return literary bounds mapped to the native render raster."""
        return self.output_region

    @property
    def requires_resampling(self) -> bool:
        """Whether the complete native presentation must later be resampled."""
        return self.native_render_size != self.output_size


def validate_requested_size(requested_size: object) -> tuple[int, int]:
    """Validate a positive integer landscape raster and return immutable dimensions."""
    if (
        not isinstance(requested_size, (tuple, list))
        or len(requested_size) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in requested_size)
    ):
        raise PresentationGeometryError("requested size must contain two positive integer pixel dimensions")

    width, height = requested_size
    if width <= height:
        raise PresentationGeometryError("requested raster dimensions must be landscape")
    return width, height


def _aspect_ratio_for_size(size: tuple[int, int], *, legacy_only: bool) -> str | None:
    width, height = size
    return next(
        (
            aspect_ratio
            for aspect_ratio, aspect in SUPPORTED_PRESENTATION_ASPECTS.items()
            if (not legacy_only or aspect_ratio in _LEGACY_ASPECT_RATIOS)
            and width * aspect.height == height * aspect.width
        ),
        None,
    )


def validate_output_size(output_size: object) -> tuple[int, int]:
    """Validate a positive integer landscape size at an exactly supported legacy ratio."""
    if (
        not isinstance(output_size, (tuple, list))
        or len(output_size) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in output_size)
    ):
        raise PresentationGeometryError("output size must contain two positive integer pixel dimensions")

    width, height = output_size
    if width <= height or _aspect_ratio_for_size((width, height), legacy_only=True) is None:
        raise PresentationGeometryError("output aspect ratio must exactly match landscape 4:3, 16:9, or 16:10")
    return width, height


def working_canvas_for_aspect(aspect_ratio: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return canonical working geometry for an explicitly declared aspect ratio."""
    try:
        aspect = SUPPORTED_PRESENTATION_ASPECTS[aspect_ratio]
    except (KeyError, TypeError):
        raise PresentationGeometryError(f"unsupported presentation aspect ratio: {aspect_ratio!r}") from None
    return aspect.working_size, aspect.crop_origin


def working_canvas_for_output(output_size: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return legacy exact-ratio working geometry for a configured output size."""
    width, height = validate_output_size(output_size)
    aspect_ratio = _aspect_ratio_for_size((width, height), legacy_only=True)
    assert aspect_ratio is not None
    return working_canvas_for_aspect(aspect_ratio)


def validate_presentation_insets(insets: PresentationInsets, working_size: tuple[int, int]) -> PixelBounds:
    """Return working-space rectangle bounds after validating independent insets."""
    if not isinstance(insets, PresentationInsets):
        raise PresentationGeometryError("presentation insets must define left, right, top, and bottom")
    values = (insets.left, insets.right, insets.top, insets.bottom)
    if any(type(value) is not int or value < 0 for value in values):
        raise PresentationGeometryError("presentation insets must be nonnegative integers")
    width, height = working_size
    bounds = (insets.left, insets.top, width - insets.right, height - insets.bottom)
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise PresentationGeometryError(
            f"presentation insets leave no positive literary rectangle on the {width} x {height} working canvas"
        )
    return bounds


def round_half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def resolve_aspect_first_geometry(
    output_specification: ResolvedOutputSpecification,
    insets: PresentationInsets,
) -> PresentationGeometry:
    """Map canonical aspect-first geometry to the specification's native render raster."""
    if not isinstance(output_specification, ResolvedOutputSpecification):
        raise PresentationGeometryError("output specification must be resolved before geometry")
    working_size, crop_origin = working_canvas_for_aspect(output_specification.aspect_ratio)
    working_region = validate_presentation_insets(insets, working_size)
    width, height = working_size
    native_width, native_height = output_specification.native_render_size

    left, top, right, bottom = working_region
    output_region = (
        round_half_up(left * native_width, width),
        round_half_up(top * native_height, height),
        round_half_up(right * native_width, width),
        round_half_up(bottom * native_height, height),
    )
    if (
        output_region[0] < 0
        or output_region[1] < 0
        or output_region[2] > native_width
        or output_region[3] > native_height
        or output_region[2] <= output_region[0]
        or output_region[3] <= output_region[1]
    ):
        raise PresentationGeometryError("presentation insets map to degenerate or out-of-bounds output geometry")

    return PresentationGeometry(
        reference_size=REFERENCE_SIZE,
        working_size=working_size,
        crop_origin=crop_origin,
        output_size=output_specification.requested_size,
        working_region=working_region,
        output_region=output_region,
        aspect_ratio=output_specification.aspect_ratio,
        native_render_size=output_specification.native_render_size,
    )


def resolve_presentation_geometry(
    output_size: tuple[int, int],
    insets: PresentationInsets,
) -> PresentationGeometry:
    """Resolve legacy exact-ratio output geometry through the aspect-first core."""
    output_size = validate_output_size(output_size)
    aspect_ratio = _aspect_ratio_for_size(output_size, legacy_only=True)
    assert aspect_ratio is not None
    return resolve_aspect_first_geometry(ResolvedOutputSpecification(aspect_ratio, output_size), insets)


__all__ = [
    "DEFAULT_OUTPUT_SIZE",
    "DEFAULT_PRESENTATION_INSETS",
    "PixelBounds",
    "PresentationAspect",
    "PresentationGeometry",
    "PresentationGeometryError",
    "PresentationInsets",
    "REFERENCE_SIZE",
    "ResolvedOutputSpecification",
    "SUPPORTED_PRESENTATION_ASPECTS",
    "resolve_aspect_first_geometry",
    "resolve_presentation_geometry",
    "round_half_up",
    "validate_output_size",
    "validate_presentation_insets",
    "validate_requested_size",
    "working_canvas_for_aspect",
    "working_canvas_for_output",
]

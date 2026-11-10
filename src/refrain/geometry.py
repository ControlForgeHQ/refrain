"""Resolved presentation geometry independent of rendering and display hardware."""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from types import MappingProxyType
from typing import Mapping

REFERENCE_SIZE = (3840, 2400)
DEFAULT_PRESENTATION_INSETS = (384, 384, 324, 324)

PixelBounds = tuple[int, int, int, int]


class PresentationGeometryError(ValueError):
    """Raised when output dimensions or literary geometry are invalid."""


@dataclass(frozen=True)
class PresentationAspect:
    """Canonical geometry for one supported presentation aspect ratio."""

    width: int
    height: int
    design_canvas_size: tuple[int, int]
    crop_origin: tuple[int, int]

    @property
    def reduced_ratio(self) -> tuple[int, int]:
        """Return primitive integer components for the presentation-canvas lattice."""
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
    """Declared presentation aspect and exact requested output raster."""

    aspect_ratio: str
    requested_output_size: tuple[int, int]

    def __post_init__(self) -> None:
        if not isinstance(self.aspect_ratio, str) or self.aspect_ratio not in SUPPORTED_PRESENTATION_ASPECTS:
            raise PresentationGeometryError(f"unsupported presentation aspect ratio: {self.aspect_ratio!r}")
        object.__setattr__(self, "requested_output_size", validate_requested_size(self.requested_output_size))

    @property
    def presentation_canvas_size(self) -> tuple[int, int]:
        """Return the nearest positive integer raster at the declared aspect ratio."""
        aspect = SUPPORTED_PRESENTATION_ASPECTS[self.aspect_ratio]
        width, height = self.requested_output_size
        if width * aspect.height == height * aspect.width:
            return self.requested_output_size

        ratio_width, ratio_height = aspect.reduced_ratio
        projected_scale = round_half_up(
            ratio_width * width + ratio_height * height,
            ratio_width * ratio_width + ratio_height * ratio_height,
        )
        scale = max(1, projected_scale)
        return ratio_width * scale, ratio_height * scale

    @property
    def requires_output_resize(self) -> bool:
        return self.presentation_canvas_size != self.requested_output_size


@dataclass(frozen=True)
class PresentationInsets:
    """Independent design-canvas pixel distances from each edge."""

    left: int
    right: int
    top: int
    bottom: int


@dataclass(frozen=True)
class PresentationGeometry:
    """Design-canvas, presentation-canvas, requested-output, and literary geometry."""

    reference_size: tuple[int, int]
    design_canvas_size: tuple[int, int]
    design_canvas_crop_origin: tuple[int, int]
    presentation_canvas_size: tuple[int, int]
    requested_output_size: tuple[int, int]
    design_literary_bounds: PixelBounds
    presentation_literary_bounds: PixelBounds
    aspect_ratio: str

    @property
    def requires_output_resize(self) -> bool:
        """Whether the complete presentation canvas must be resized for output."""
        return self.presentation_canvas_size != self.requested_output_size


def validate_requested_size(requested_output_size: object) -> tuple[int, int]:
    """Validate positive integer landscape output dimensions."""
    if (
        not isinstance(requested_output_size, (tuple, list))
        or len(requested_output_size) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in requested_output_size)
    ):
        raise PresentationGeometryError("requested output size must contain two positive integer pixel dimensions")

    width, height = requested_output_size
    if width <= height:
        raise PresentationGeometryError("requested output dimensions must be landscape")
    return width, height


def design_canvas_for_aspect(aspect_ratio: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return canonical design-canvas geometry for an explicitly declared aspect ratio."""
    try:
        aspect = SUPPORTED_PRESENTATION_ASPECTS[aspect_ratio]
    except (KeyError, TypeError):
        raise PresentationGeometryError(f"unsupported presentation aspect ratio: {aspect_ratio!r}") from None
    return aspect.design_canvas_size, aspect.crop_origin


def validate_presentation_insets(insets: PresentationInsets, design_canvas_size: tuple[int, int]) -> PixelBounds:
    """Return design-space rectangle bounds after validating independent insets."""
    if not isinstance(insets, PresentationInsets):
        raise PresentationGeometryError("presentation insets must define left, right, top, and bottom")
    values = (insets.left, insets.right, insets.top, insets.bottom)
    if any(type(value) is not int or value < 0 for value in values):
        raise PresentationGeometryError("presentation insets must be nonnegative integers")
    width, height = design_canvas_size
    bounds = (insets.left, insets.top, width - insets.right, height - insets.bottom)
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise PresentationGeometryError(
            f"presentation insets leave no positive literary rectangle on the {width} x {height} design canvas"
        )
    return bounds


def round_half_up(numerator: int, denominator: int) -> int:
    """Round a nonnegative rational value to the nearest integer, ties upward."""
    return (2 * numerator + denominator) // (2 * denominator)


def scale_design_geometry_to_presentation(
    design_literary_bounds: PixelBounds,
    design_canvas_size: tuple[int, int],
    presentation_canvas_size: tuple[int, int],
) -> PixelBounds:
    """Map design-space rectangle edges independently to presentation-canvas pixels."""
    design_width, design_height = design_canvas_size
    presentation_width, presentation_height = presentation_canvas_size
    left, top, right, bottom = design_literary_bounds
    bounds = (
        round_half_up(left * presentation_width, design_width),
        round_half_up(top * presentation_height, design_height),
        round_half_up(right * presentation_width, design_width),
        round_half_up(bottom * presentation_height, design_height),
    )
    if (
        bounds[0] < 0
        or bounds[1] < 0
        or bounds[2] > presentation_width
        or bounds[3] > presentation_height
        or bounds[2] <= bounds[0]
        or bounds[3] <= bounds[1]
    ):
        raise PresentationGeometryError(
            "presentation insets map to degenerate or out-of-bounds presentation-canvas geometry"
        )
    return bounds


def resolve_presentation_geometry(
    output_specification: ResolvedOutputSpecification,
    insets: PresentationInsets,
) -> PresentationGeometry:
    """Resolve design and presentation geometry for one explicit output specification."""
    if not isinstance(output_specification, ResolvedOutputSpecification):
        raise PresentationGeometryError("output specification must be resolved before geometry")
    design_canvas_size, crop_origin = design_canvas_for_aspect(output_specification.aspect_ratio)
    design_literary_bounds = validate_presentation_insets(insets, design_canvas_size)
    presentation_canvas_size = output_specification.presentation_canvas_size
    presentation_literary_bounds = scale_design_geometry_to_presentation(
        design_literary_bounds,
        design_canvas_size,
        presentation_canvas_size,
    )
    return PresentationGeometry(
        reference_size=REFERENCE_SIZE,
        design_canvas_size=design_canvas_size,
        design_canvas_crop_origin=crop_origin,
        presentation_canvas_size=presentation_canvas_size,
        requested_output_size=output_specification.requested_output_size,
        design_literary_bounds=design_literary_bounds,
        presentation_literary_bounds=presentation_literary_bounds,
        aspect_ratio=output_specification.aspect_ratio,
    )


__all__ = [
    "DEFAULT_PRESENTATION_INSETS",
    "PixelBounds",
    "PresentationAspect",
    "PresentationGeometry",
    "PresentationGeometryError",
    "PresentationInsets",
    "REFERENCE_SIZE",
    "ResolvedOutputSpecification",
    "SUPPORTED_PRESENTATION_ASPECTS",
    "resolve_presentation_geometry",
    "round_half_up",
    "scale_design_geometry_to_presentation",
    "validate_presentation_insets",
    "validate_requested_size",
    "design_canvas_for_aspect",
]

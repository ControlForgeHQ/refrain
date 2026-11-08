"""Resolved presentation geometry independent of rendering and display hardware."""

from __future__ import annotations

from dataclasses import dataclass

REFERENCE_SIZE = (3840, 2400)
DEFAULT_OUTPUT_SIZE = (1920, 1080)
DEFAULT_PRESENTATION_INSETS = (384, 384, 324, 324)

PixelBounds = tuple[int, int, int, int]


class PresentationGeometryError(ValueError):
    """Raised when output dimensions or literary geometry are invalid."""


@dataclass(frozen=True)
class PresentationInsets:
    """Independent working-canvas pixel distances from each edge."""

    left: int
    right: int
    top: int
    bottom: int


@dataclass(frozen=True)
class PresentationGeometry:
    """Reference, working, final-output, and effective literary dimensions."""

    reference_size: tuple[int, int]
    working_size: tuple[int, int]
    crop_origin: tuple[int, int]
    output_size: tuple[int, int]
    working_region: PixelBounds
    output_region: PixelBounds


def validate_output_size(output_size: object) -> tuple[int, int]:
    """Validate a positive integer landscape size at an exactly supported ratio."""
    if (
        not isinstance(output_size, (tuple, list))
        or len(output_size) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in output_size)
    ):
        raise PresentationGeometryError("output size must contain two positive integer pixel dimensions")

    width, height = output_size
    if width * 3 == height * 4:
        return width, height
    if width * 9 == height * 16:
        return width, height
    if width * 10 == height * 16:
        return width, height
    raise PresentationGeometryError("output aspect ratio must exactly match landscape 4:3, 16:9, or 16:10")


def working_canvas_for_output(output_size: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return the largest centered supported-ratio canvas and its reference origin."""
    width, height = validate_output_size(output_size)
    if width * 3 == height * 4:
        working_size = (3200, 2400)
    elif width * 9 == height * 16:
        working_size = (3840, 2160)
    else:
        working_size = REFERENCE_SIZE
    crop_origin = ((REFERENCE_SIZE[0] - working_size[0]) // 2, (REFERENCE_SIZE[1] - working_size[1]) // 2)
    return working_size, crop_origin


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


def resolve_presentation_geometry(
    output_size: tuple[int, int],
    insets: PresentationInsets,
) -> PresentationGeometry:
    """Resolve centered working geometry and deterministically map its literary bounds."""
    output_size = validate_output_size(output_size)
    working_size, crop_origin = working_canvas_for_output(output_size)
    working_region = validate_presentation_insets(insets, working_size)
    width, height = working_size
    output_width, output_height = output_size
    if output_width * height != output_height * width:
        raise PresentationGeometryError("output and working-canvas aspect ratios must match exactly")

    left, top, right, bottom = working_region
    output_region = (
        round_half_up(left * output_width, width),
        round_half_up(top * output_height, height),
        round_half_up(right * output_width, width),
        round_half_up(bottom * output_height, height),
    )
    if (
        output_region[0] < 0
        or output_region[1] < 0
        or output_region[2] > output_width
        or output_region[3] > output_height
        or output_region[2] <= output_region[0]
        or output_region[3] <= output_region[1]
    ):
        raise PresentationGeometryError("presentation insets map to degenerate or out-of-bounds output geometry")

    return PresentationGeometry(
        reference_size=REFERENCE_SIZE,
        working_size=working_size,
        crop_origin=crop_origin,
        output_size=output_size,
        working_region=working_region,
        output_region=output_region,
    )


__all__ = [
    "DEFAULT_OUTPUT_SIZE",
    "DEFAULT_PRESENTATION_INSETS",
    "PixelBounds",
    "PresentationGeometry",
    "PresentationGeometryError",
    "PresentationInsets",
    "REFERENCE_SIZE",
    "round_half_up",
    "resolve_presentation_geometry",
    "validate_output_size",
    "validate_presentation_insets",
    "working_canvas_for_output",
]

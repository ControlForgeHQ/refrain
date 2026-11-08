from __future__ import annotations

import pytest

from refrain.geometry import (
    DEFAULT_OUTPUT_SIZE,
    DEFAULT_PRESENTATION_INSETS,
    REFERENCE_SIZE,
    PresentationGeometryError,
    PresentationInsets,
    resolve_presentation_geometry,
    validate_output_size,
    working_canvas_for_output,
)


@pytest.mark.parametrize(
    ("output_size", "working_size", "crop_origin"),
    [
        ((1600, 1200), (3200, 2400), (320, 0)),
        ((1920, 1080), (3840, 2160), (0, 120)),
        ((3840, 2400), (3840, 2400), (0, 0)),
        ((808, 505), (3840, 2400), (0, 0)),
    ],
)
def test_working_canvas_is_derived_from_exact_output_aspect_ratio(
    output_size: tuple[int, int], working_size: tuple[int, int], crop_origin: tuple[int, int]
) -> None:
    assert working_canvas_for_output(output_size) == (working_size, crop_origin)


def test_reference_and_documented_defaults_are_fixed() -> None:
    assert REFERENCE_SIZE == (3840, 2400)
    assert DEFAULT_OUTPUT_SIZE == (1920, 1080)
    assert DEFAULT_PRESENTATION_INSETS == (384, 384, 324, 324)


@pytest.mark.parametrize("output_size", [(1000, 562), (1365, 768), (1920, 1201)])
def test_supported_output_ratios_are_compared_exactly(output_size: tuple[int, int]) -> None:
    with pytest.raises(PresentationGeometryError, match="exactly"):
        validate_output_size(output_size)


@pytest.mark.parametrize(
    "output_size",
    [
        (0, 1080),
        (-16, 9),
        (16.0, 9),
        (True, 9),
        (16,),
        (16, 9, 1),
        "16:9",
        (1, 1),
        (9, 16),
    ],
)
def test_invalid_output_dimensions_or_aspect_ratios_are_rejected(output_size: object) -> None:
    with pytest.raises(PresentationGeometryError):
        validate_output_size(output_size)


@pytest.mark.parametrize(
    ("output_size", "expected_working", "expected_output"),
    [
        ((1600, 1200), (3200, 2400), (80, 60, 1520, 1140)),
        ((1920, 1080), (3840, 2160), (80, 60, 1840, 1020)),
        ((3840, 2400), (3840, 2400), (160, 120, 3680, 2280)),
    ],
)
def test_insets_are_applied_to_the_working_canvas_before_output_mapping(
    output_size: tuple[int, int],
    expected_working: tuple[int, int],
    expected_output: tuple[int, int, int, int],
) -> None:
    geometry = resolve_presentation_geometry(output_size, PresentationInsets(160, 160, 120, 120))

    assert geometry.reference_size == REFERENCE_SIZE
    assert geometry.working_size == expected_working
    assert geometry.output_region == expected_output


def test_exact_half_pixels_round_up_and_shared_edges_are_deterministic() -> None:
    geometry = resolve_presentation_geometry((8, 5), PresentationInsets(240, 240, 240, 240))

    assert geometry.working_region == (240, 240, 3600, 2160)
    assert geometry.output_region == (1, 1, 8, 5)
    assert geometry == resolve_presentation_geometry((8, 5), PresentationInsets(240, 240, 240, 240))


def test_fractional_edges_map_to_nearest_final_pixel() -> None:
    geometry = resolve_presentation_geometry((16, 10), PresentationInsets(384, 384, 324, 324))

    assert geometry.output_region == (2, 1, 14, 9)


def test_positive_working_rectangle_that_collapses_after_mapping_is_rejected() -> None:
    with pytest.raises(PresentationGeometryError, match="degenerate"):
        resolve_presentation_geometry((8, 5), PresentationInsets(1919, 1920, 0, 0))


@pytest.mark.parametrize(
    "insets",
    [
        PresentationInsets(-1, 0, 0, 0),
        PresentationInsets(True, 0, 0, 0),
        PresentationInsets(1.5, 0, 0, 0),  # type: ignore[arg-type]
    ],
)
def test_invalid_insets_are_rejected(insets: PresentationInsets) -> None:
    with pytest.raises(PresentationGeometryError, match="nonnegative integers"):
        resolve_presentation_geometry((1920, 1080), insets)

from __future__ import annotations

import pytest

from refrain.geometry import (
    DEFAULT_OUTPUT_SIZE,
    DEFAULT_PRESENTATION_INSETS,
    REFERENCE_SIZE,
    SUPPORTED_PRESENTATION_ASPECTS,
    PresentationGeometryError,
    PresentationInsets,
    ResolvedOutputSpecification,
    resolve_aspect_first_geometry,
    resolve_presentation_geometry,
    validate_output_size,
    working_canvas_for_aspect,
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


@pytest.mark.parametrize(
    ("aspect_ratio", "working_size", "crop_origin"),
    [
        ("4:3", (3200, 2400), (320, 0)),
        ("5:3", (3840, 2304), (0, 48)),
        ("16:9", (3840, 2160), (0, 120)),
        ("16:10", (3840, 2400), (0, 0)),
    ],
)
def test_canonical_working_geometry_is_defined_for_each_supported_aspect(
    aspect_ratio: str, working_size: tuple[int, int], crop_origin: tuple[int, int]
) -> None:
    assert working_canvas_for_aspect(aspect_ratio) == (working_size, crop_origin)
    assert aspect_ratio in SUPPORTED_PRESENTATION_ASPECTS


@pytest.mark.parametrize(
    ("aspect_ratio", "requested_size"),
    [
        ("4:3", (1600, 1200)),
        ("4:3", (3200, 2400)),
        ("5:3", (1000, 600)),
        ("16:9", (1920, 1080)),
        ("16:10", (1280, 800)),
    ],
)
def test_exact_aspect_requests_are_the_native_render_resolution(aspect_ratio, requested_size) -> None:
    specification = ResolvedOutputSpecification(aspect_ratio, requested_size)

    assert specification.native_render_size == requested_size
    assert not specification.requires_resampling


def test_mismatched_requested_resolution_uses_nearest_native_aspect_raster() -> None:
    specification = ResolvedOutputSpecification("5:3", (1920, 1080))

    assert specification.native_render_size == (1890, 1134)
    assert specification.requires_resampling


def test_mismatched_sixteen_ten_request_uses_reduced_native_ratio_lattice() -> None:
    aspect = SUPPORTED_PRESENTATION_ASPECTS["16:10"]
    specification = ResolvedOutputSpecification("16:10", (809, 505))

    assert aspect.reduced_ratio == (8, 5)
    assert specification.native_render_size == (808, 505)
    assert specification.requires_resampling


def test_native_resolution_exact_tie_rounds_up_to_the_larger_raster() -> None:
    specification = ResolvedOutputSpecification("5:3", (9, 2))

    assert specification.native_render_size == (10, 6)


def test_very_small_positive_requested_raster_uses_smallest_native_raster() -> None:
    specification = ResolvedOutputSpecification("16:9", (2, 1))

    assert specification.native_render_size == (16, 9)


def test_output_specifications_are_immutable_hashable_and_deduplicable() -> None:
    first = ResolvedOutputSpecification("16:9", [1920, 1080])
    second = ResolvedOutputSpecification("16:9", (1920, 1080))

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
    assert first.requested_size == (1920, 1080)


@pytest.mark.parametrize("aspect_ratio", ["5/3", "7:4", "", None, True])
def test_invalid_declared_aspect_ratios_are_rejected(aspect_ratio) -> None:
    with pytest.raises(PresentationGeometryError, match="unsupported"):
        ResolvedOutputSpecification(aspect_ratio, (1000, 600))


@pytest.mark.parametrize(
    "requested_size",
    [
        (0, 1),
        (-5, 3),
        (5, 0),
        (5.0, 3),
        (True, 3),
        (5,),
        (5, 3, 1),
        "5:3",
        (3, 5),
        (5, 5),
    ],
)
def test_invalid_requested_raster_dimensions_are_rejected(requested_size) -> None:
    with pytest.raises(PresentationGeometryError):
        ResolvedOutputSpecification("5:3", requested_size)


@pytest.mark.parametrize(
    ("aspect_ratio", "requested_size", "expected_working", "expected_native", "expected_region"),
    [
        ("4:3", (1600, 1200), (3200, 2400), (1600, 1200), (192, 162, 1408, 1038)),
        ("5:3", (1000, 600), (3840, 2304), (1000, 600), (100, 84, 900, 516)),
        ("16:9", (1920, 1080), (3840, 2160), (1920, 1080), (192, 162, 1728, 918)),
        ("16:10", (1280, 800), (3840, 2400), (1280, 800), (128, 108, 1152, 692)),
        ("5:3", (1920, 1080), (3840, 2304), (1890, 1134), (189, 159, 1701, 975)),
    ],
)
def test_aspect_first_geometry_maps_insets_to_native_resolution(
    aspect_ratio, requested_size, expected_working, expected_native, expected_region
) -> None:
    geometry = resolve_aspect_first_geometry(
        ResolvedOutputSpecification(aspect_ratio, requested_size),
        PresentationInsets(384, 384, 324, 324),
    )

    assert geometry.aspect_ratio == aspect_ratio
    assert geometry.working_size == expected_working
    assert geometry.requested_size == requested_size
    assert geometry.native_render_size == expected_native
    assert geometry.native_render_region == expected_region
    assert geometry.requires_resampling == (expected_native != requested_size)


def test_aspect_first_geometry_rejects_regions_that_collapse_after_mapping() -> None:
    with pytest.raises(PresentationGeometryError, match="degenerate"):
        resolve_aspect_first_geometry(
            ResolvedOutputSpecification("16:10", (4, 3)),
            PresentationInsets(1919, 1920, 0, 0),
        )


def test_legacy_output_validation_does_not_expose_five_three() -> None:
    with pytest.raises(PresentationGeometryError, match="4:3, 16:9, or 16:10"):
        validate_output_size((1500, 900))


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

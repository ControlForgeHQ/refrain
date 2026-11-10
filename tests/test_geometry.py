from __future__ import annotations

import pytest

from refrain.geometry import (
    PresentationGeometryError,
    PresentationInsets,
    ResolvedOutputSpecification,
    resolve_presentation_geometry,
    round_half_up,
    design_canvas_for_aspect,
)


@pytest.mark.parametrize(
    ("aspect_ratio", "expected_design_size"),
    [
        ("4:3", (3200, 2400)),
        ("5:3", (3840, 2304)),
        ("16:9", (3840, 2160)),
        ("16:10", (3840, 2400)),
    ],
)
def test_design_canvas_sizes_are_aspect_specific(aspect_ratio, expected_design_size) -> None:
    specification = ResolvedOutputSpecification(aspect_ratio, expected_design_size)

    assert design_canvas_for_aspect(aspect_ratio)[0] == expected_design_size


def test_exact_aspect_specification_uses_requested_size_for_presentation_and_output() -> None:
    specification = ResolvedOutputSpecification("16:9", (1920, 1080))
    geometry = resolve_presentation_geometry(specification, PresentationInsets(384, 384, 324, 324))

    assert geometry.design_canvas_size == (3840, 2160)
    assert specification.presentation_canvas_size == (1920, 1080)
    assert specification.requested_output_size == (1920, 1080)
    assert geometry.design_literary_bounds == (384, 324, 3456, 1836)
    assert geometry.presentation_literary_bounds == (192, 162, 1728, 918)


def test_mismatched_aspect_specification_derives_exact_ratio_presentation_canvas() -> None:
    specification = ResolvedOutputSpecification("4:3", (1600, 1190))
    geometry = resolve_presentation_geometry(specification, PresentationInsets(384, 384, 324, 324))

    assert geometry.design_canvas_size == (3200, 2400)
    assert specification.presentation_canvas_size == (1596, 1197)
    assert specification.requested_output_size == (1600, 1190)
    assert geometry.presentation_literary_bounds == (192, 162, 1404, 1035)


@pytest.mark.parametrize(
    "requested_size",
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
def test_invalid_requested_output_dimensions_are_rejected(requested_size: object) -> None:
    with pytest.raises(PresentationGeometryError):
        ResolvedOutputSpecification("16:9", requested_size)


def test_unsupported_aspect_is_rejected() -> None:
    with pytest.raises(PresentationGeometryError):
        ResolvedOutputSpecification("3:2", (1500, 1000))


def test_half_up_rounding_is_deterministic() -> None:
    assert round_half_up(1, 2) == 1
    assert round_half_up(3, 2) == 2
    assert round_half_up(5, 2) == 3


def test_presentation_geometry_rejects_bounds_that_collapse_after_mapping() -> None:
    with pytest.raises(PresentationGeometryError, match="degenerate"):
        resolve_presentation_geometry(
            ResolvedOutputSpecification("16:10", (4, 3)),
            PresentationInsets(1919, 1920, 0, 0),
        )


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
        resolve_presentation_geometry(ResolvedOutputSpecification("16:9", (1920, 1080)), insets)

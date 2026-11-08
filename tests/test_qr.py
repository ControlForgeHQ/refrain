from __future__ import annotations

import pytest
import qrcode

from refrain.qr import (
    PRODUCTION_QR_PARAMETERS,
    QR_ALLOCATION_SIZE,
    REPOSITORY_URL,
    QRCodeGenerationError,
    QRCodeParameters,
    QRCodePlacementError,
    qr_parameters_from_metadata,
    qr_parameters_to_metadata,
    render_qr_code,
    resolve_qr_placement,
)
from refrain.qr_diagnostic import QRCalibrationParameters, create_qr_calibration_image


def test_production_qr_defaults_have_exact_geometry_and_pixel_modules() -> None:
    result = render_qr_code(PRODUCTION_QR_PARAMETERS, (1600, 1200))
    expected = qrcode.QRCode(version=4, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
    expected.add_data(REPOSITORY_URL.encode("utf-8"), optimize=0)
    expected.make(fit=False)
    try:
        geometry = result.geometry
        assert geometry.version == 4
        assert geometry.symbol_modules == 33
        assert geometry.footprint_size == (123, 123)
        assert geometry.bounds == (1437, 1037, 1559, 1159)
        assert result.image.mode == "RGB"
        assert result.image.size == (123, 123)
        assert set(result.image.get_flattened_data()) <= {(0, 0, 0), (255, 255, 255)}

        quiet = geometry.quiet_zone_pixels
        assert quiet == 12
        assert result.image.getpixel((0, 0)) == (255, 255, 255)
        for row_index, row in enumerate(expected.modules):
            for column_index, dark in enumerate(row):
                x = quiet + column_index * 3
                y = quiet + row_index * 3
                expected_pixel = (0, 0, 0) if dark else (255, 255, 255)
                assert all(
                    result.image.getpixel((x + dx, y + dy)) == expected_pixel for dx in range(3) for dy in range(3)
                )
        for y in range(quiet):
            assert all(result.image.getpixel((x, y)) == (255, 255, 255) for x in range(123))
            assert all(result.image.getpixel((x, 122 - y)) == (255, 255, 255) for x in range(123))
        for x in range(quiet):
            assert all(result.image.getpixel((x, y)) == (255, 255, 255) for y in range(123))
            assert all(result.image.getpixel((122 - x, y)) == (255, 255, 255) for y in range(123))
    finally:
        result.image.close()


def test_explicit_url_and_absent_url_fallback_match_standalone_qr() -> None:
    parameters = QRCodeParameters(
        url="https://example.org/alternate",
        version=4,
        error_correction="M",
        module_size=3,
        quiet_zone=4,
        right_offset=40,
        bottom_offset=40,
    )
    explicit = render_qr_code(parameters, (1600, 1200))
    fallback = render_qr_code(
        QRCodeParameters(
            url=None,
            version=4,
            error_correction="M",
            module_size=3,
            quiet_zone=4,
            right_offset=40,
            bottom_offset=40,
        ),
        (1600, 1200),
    )
    default_diagnostic = create_qr_calibration_image(
        QRCalibrationParameters(
            payload=parameters.url,
            version=parameters.version,
            error_correction=parameters.error_correction,
            module_size=parameters.module_size,
            quiet_zone=parameters.quiet_zone,
            right_offset=parameters.right_offset,
            bottom_offset=parameters.bottom_offset,
        )
    )
    diagnostic = create_qr_calibration_image(
        QRCalibrationParameters(
            payload=parameters.url,
            version=parameters.version,
            error_correction=parameters.error_correction,
            module_size=parameters.module_size,
            quiet_zone=parameters.quiet_zone,
            right_offset=parameters.right_offset,
            bottom_offset=parameters.bottom_offset,
        ),
        output_size=(1600, 1200),
    )
    try:
        assert default_diagnostic.geometry.image_size == (1920, 1080)
        assert diagnostic.geometry.image_size == (1600, 1200)
        assert explicit.geometry.version == fallback.geometry.version == 4
        with diagnostic.image.crop(
            (
                explicit.geometry.bounds[0],
                explicit.geometry.bounds[1],
                explicit.geometry.bounds[2] + 1,
                explicit.geometry.bounds[3] + 1,
            )
        ) as diagnostic_footprint:
            assert explicit.image.tobytes() == diagnostic_footprint.tobytes()
        assert explicit.image.tobytes() != fallback.image.tobytes()
        assert qr_parameters_to_metadata(QRCodeParameters(None, 4, "M", 3, 4, 40, 40))["url"] == REPOSITORY_URL
        assert qr_parameters_from_metadata(qr_parameters_to_metadata(parameters)) == parameters
    finally:
        explicit.image.close()
        fallback.image.close()
        default_diagnostic.image.close()
        diagnostic.image.close()


def test_qr_geometry_and_capacity_failures_are_actionable() -> None:
    with pytest.raises(QRCodeGenerationError, match=r"123 x 123.*available.*100 x 100"):
        render_qr_code(PRODUCTION_QR_PARAMETERS, (100, 100))
    with pytest.raises(QRCodeGenerationError, match=r"available capacity.*version 4.*shorten the payload"):
        render_qr_code(
            QRCodeParameters("x" * 300, 4, "M", 3, 4, 40, 40),
            (1600, 1200),
        )


@pytest.mark.parametrize(
    ("output_size", "working_size", "allocation_bounds", "module_size"),
    [
        ((1600, 1200), (3200, 2400), (1467, 1067, 1590, 1190), 3),
        ((1920, 1080), (3840, 2160), (1787, 947, 1910, 1070), 3),
        ((800, 600), (3200, 2400), (734, 534, 795, 595), 1),
        ((3840, 2160), (3840, 2160), (3574, 1894, 3820, 2140), 6),
        ((3840, 2400), (3840, 2400), (3574, 2134, 3820, 2380), 6),
    ],
)
def test_fixed_working_allocation_maps_to_output_and_selects_largest_module(
    output_size: tuple[int, int],
    working_size: tuple[int, int],
    allocation_bounds: tuple[int, int, int, int],
    module_size: int,
) -> None:
    placement = resolve_qr_placement(output_size)

    assert QR_ALLOCATION_SIZE == 246
    assert (placement.working_bounds[2] - placement.working_bounds[0]) == 246
    assert (placement.working_bounds[3] - placement.working_bounds[1]) == 246
    assert placement.image_size == output_size
    assert placement.allocation_bounds == allocation_bounds
    assert placement.module_size == module_size
    assert placement.footprint_size == (module_size * 41, module_size * 41)
    assert placement.working_bounds[2] <= working_size[0]
    assert placement.working_bounds[3] <= working_size[1]


@pytest.mark.parametrize(
    ("positioning", "expected"),
    [
        ({"qr_from_left": 20, "qr_from_top": 20}, (20, 20, 266, 266)),
        ({"qr_from_right": 20, "qr_from_top": 20}, (2934, 20, 3180, 266)),
        ({"qr_from_left": 20, "qr_from_bottom": 20}, (20, 2134, 266, 2380)),
        ({"qr_centered": "horizontal", "qr_from_top": 20}, (1477, 20, 1723, 266)),
        ({"qr_centered": "horizontal", "qr_from_bottom": 20}, (1477, 2134, 1723, 2380)),
        ({"qr_centered": "vertical", "qr_from_left": 20}, (20, 1077, 266, 1323)),
        ({"qr_centered": "vertical", "qr_from_right": 20}, (2934, 1077, 3180, 1323)),
        ({"qr_from_left": 0, "qr_from_top": 0}, (0, 0, 246, 246)),
        ({"qr_from_left": 2954, "qr_from_top": 2154}, (2954, 2154, 3200, 2400)),
    ],
)
def test_qr_positioning_methods_resolve_each_axis_independently(
    positioning: dict[str, object], expected: tuple[int, int, int, int]
) -> None:
    assert resolve_qr_placement((1600, 1200), positioning).working_bounds == expected


@pytest.mark.parametrize(
    ("output_size", "horizontal_bounds", "vertical_bounds"),
    [
        ((1600, 1200), (1477, 20, 1723, 266), (20, 1077, 266, 1323)),
        ((1920, 1080), (1797, 20, 2043, 266), (20, 957, 266, 1203)),
        ((3840, 2400), (1797, 20, 2043, 266), (20, 1077, 266, 1323)),
    ],
)
def test_centering_uses_the_ratio_specific_working_canvas(
    output_size: tuple[int, int],
    horizontal_bounds: tuple[int, int, int, int],
    vertical_bounds: tuple[int, int, int, int],
) -> None:
    horizontal = resolve_qr_placement(output_size, {"qr_centered": "horizontal", "qr_from_top": 20})
    vertical = resolve_qr_placement(output_size, {"qr_from_left": 20, "qr_centered": "vertical"})

    assert horizontal.working_bounds == horizontal_bounds
    assert vertical.working_bounds == vertical_bounds


@pytest.mark.parametrize(
    "positioning",
    [
        {"qr_from_left": -1},
        {"qr_from_right": True},
        {"qr_from_top": 1.5},
        {"qr_from_bottom": "20"},
        {"qr_from_left": None},
        {"qr_from_left": 20, "qr_from_right": 20},
        {"qr_centered": "horizontal", "qr_from_left": 20},
        {"qr_centered": "vertical", "qr_from_bottom": 20},
        {"qr_centered": ["horizontal", "vertical"]},
        {"qr_centered": {"horizontal": True}},
        {"qr_centered": None},
        {"qr_centered": "both"},
        {"qr_from_right": 2955},
        {"qr_from_bottom": 2155},
    ],
)
def test_invalid_or_conflicting_qr_positioning_is_rejected(positioning: dict[str, object]) -> None:
    with pytest.raises(QRCodePlacementError):
        resolve_qr_placement((1600, 1200), positioning)


def test_small_valid_allocation_centers_footprint_with_half_up_rounding() -> None:
    placement = resolve_qr_placement((548, 411), {"qr_from_left": 1, "qr_from_top": 3})

    assert placement.allocation_bounds == (0, 1, 42, 43)
    assert placement.allocation_size == (42, 42)
    assert placement.module_size == 1
    assert placement.bounds == (1, 2, 41, 42)


def test_insufficient_output_resolution_suppresses_complete_symbol() -> None:
    with pytest.raises(QRCodePlacementError, match="complete 41-module"):
        resolve_qr_placement((80, 60))


def test_production_raster_uses_resolved_integer_fit_and_allocation() -> None:
    placement = resolve_qr_placement((1600, 1200))
    result = render_qr_code(PRODUCTION_QR_PARAMETERS, (1600, 1200), placement)
    try:
        assert result.geometry.version == 4
        assert result.geometry.symbol_modules == 33
        assert result.geometry.module_size == 3
        assert result.geometry.footprint_size == (123, 123)
        assert result.geometry.bounds == (1467, 1067, 1589, 1189)
        assert result.geometry.allocation_bounds == (1467, 1067, 1590, 1190)
        assert result.image.mode == "RGB"
        assert set(result.image.get_flattened_data()) <= {(0, 0, 0), (255, 255, 255)}
    finally:
        result.image.close()


def test_production_raster_encodes_the_fixed_repository_payload() -> None:
    placement = resolve_qr_placement((1920, 1080))
    result = render_qr_code(PRODUCTION_QR_PARAMETERS, (1920, 1080), placement)
    expected = qrcode.QRCode(version=4, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
    expected.add_data(REPOSITORY_URL.encode("utf-8"), optimize=0)
    expected.make(fit=False)
    try:
        assert result.geometry.version == 4
        assert result.geometry.symbol_modules == expected.modules_count == 33
        assert result.geometry.module_size == 3
        assert result.image.size == result.geometry.footprint_size == (123, 123)
        quiet = result.geometry.quiet_zone_pixels
        for row_index, row in enumerate(expected.modules):
            for column_index, dark in enumerate(row):
                x = quiet + column_index * 3
                y = quiet + row_index * 3
                color = (0, 0, 0) if dark else (255, 255, 255)
                assert all(result.image.getpixel((x + dx, y + dy)) == color for dx in range(3) for dy in range(3))
        assert result.image.getpixel((0, 0)) == (255, 255, 255)
        for coordinate in range(quiet):
            assert all(result.image.getpixel((x, coordinate)) == (255, 255, 255) for x in range(123))
            assert all(result.image.getpixel((x, 122 - coordinate)) == (255, 255, 255) for x in range(123))
            assert all(result.image.getpixel((coordinate, y)) == (255, 255, 255) for y in range(123))
            assert all(result.image.getpixel((122 - coordinate, y)) == (255, 255, 255) for y in range(123))
    finally:
        result.image.close()

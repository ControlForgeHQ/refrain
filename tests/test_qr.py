from __future__ import annotations

import pytest
import qrcode

from refrain.qr import (
    PRODUCTION_QR_PARAMETERS,
    REPOSITORY_URL,
    QRCodeGenerationError,
    QRCodeParameters,
    qr_parameters_from_metadata,
    qr_parameters_to_metadata,
    render_qr_code,
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
    diagnostic = create_qr_calibration_image(
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
    try:
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
        diagnostic.image.close()


def test_qr_geometry_and_capacity_failures_are_actionable() -> None:
    with pytest.raises(QRCodeGenerationError, match=r"123 x 123.*available.*100 x 100"):
        render_qr_code(PRODUCTION_QR_PARAMETERS, (100, 100))
    with pytest.raises(QRCodeGenerationError, match=r"available capacity.*version 4.*shorten the payload"):
        render_qr_code(
            QRCodeParameters("x" * 300, 4, "M", 3, 4, 40, 40),
            (1600, 1200),
        )

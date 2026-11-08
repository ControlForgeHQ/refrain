"""Standalone hardware-independent QR calibration image generation."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .geometry import DEFAULT_OUTPUT_SIZE
from .qr import (
    QRCodeGenerationError,
    QRCodeGeometry,
    QRCodeImage,
    QRCodeParameters,
    composite_qr_code,
    render_qr_code,
    validate_qr_parameters,
)

QRCalibrationError = QRCodeGenerationError


@dataclass(frozen=True)
class QRCalibrationParameters:
    payload: str = "https://example.com/"
    error_correction: str = "M"
    version: int | None = None
    module_size: int = 4
    quiet_zone: int = 4
    right_offset: int = 40
    bottom_offset: int = 40


QRCalibrationGeometry = QRCodeGeometry
QRCalibrationImage = QRCodeImage


def validate_qr_calibration_parameters(parameters: QRCalibrationParameters) -> None:
    """Validate user-controlled parameters before QR rendering or publication."""
    validate_qr_parameters(
        QRCodeParameters(
            url=parameters.payload,
            version=parameters.version,
            error_correction=parameters.error_correction,
            module_size=parameters.module_size,
            quiet_zone=parameters.quiet_zone,
            right_offset=parameters.right_offset,
            bottom_offset=parameters.bottom_offset,
        )
    )


def create_qr_calibration_image(
    parameters: QRCalibrationParameters = QRCalibrationParameters(),
    output_size: tuple[int, int] = DEFAULT_OUTPUT_SIZE,
) -> QRCalibrationImage:
    """Create the complete QR calibration canvas and its resolved pixel geometry."""
    validate_qr_calibration_parameters(parameters)
    code = render_qr_code(
        QRCodeParameters(
            url=parameters.payload,
            version=parameters.version,
            error_correction=parameters.error_correction,
            module_size=parameters.module_size,
            quiet_zone=parameters.quiet_zone,
            right_offset=parameters.right_offset,
            bottom_offset=parameters.bottom_offset,
        ),
        output_size,
    )
    image = Image.new("RGB", output_size, (255, 255, 255))
    try:
        composite_qr_code(image, code)
    except Exception:
        image.close()
        raise
    finally:
        code.image.close()
    return QRCalibrationImage(image, code.geometry)


__all__ = [
    "QRCalibrationError",
    "QRCalibrationGeometry",
    "QRCalibrationImage",
    "QRCalibrationParameters",
    "create_qr_calibration_image",
    "validate_qr_calibration_parameters",
]

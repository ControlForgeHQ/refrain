"""Hardware-independent QR calibration image generation."""

from __future__ import annotations

from dataclasses import dataclass

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q
from qrcode.exceptions import DataOverflowError

_CANVAS_SIZE = (1600, 1200)
_ERROR_CORRECTION = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}


class QRCalibrationError(ValueError):
    """Raised when QR calibration parameters cannot produce a fitting symbol."""


@dataclass(frozen=True)
class QRCalibrationParameters:
    payload: str = "https://example.com/"
    error_correction: str = "M"
    module_size: int = 4
    quiet_zone: int = 4
    right_offset: int = 40
    bottom_offset: int = 40


@dataclass(frozen=True)
class QRCalibrationGeometry:
    version: int
    symbol_modules: int
    module_size: int
    quiet_zone: int
    quiet_zone_pixels: int
    footprint_size: tuple[int, int]
    right_offset: int
    bottom_offset: int
    bounds: tuple[int, int, int, int]
    image_size: tuple[int, int]


@dataclass(frozen=True)
class QRCalibrationImage:
    image: Image.Image
    geometry: QRCalibrationGeometry


def validate_qr_calibration_parameters(parameters: QRCalibrationParameters) -> None:
    """Validate user-controlled parameters before QR rendering or publication."""
    if not isinstance(parameters.payload, str) or not parameters.payload:
        raise QRCalibrationError("QR payload must be a nonempty string")
    try:
        parameters.payload.encode("utf-8")
    except UnicodeEncodeError as error:
        raise QRCalibrationError("QR payload must be representable as UTF-8 text") from error
    if parameters.error_correction not in _ERROR_CORRECTION:
        raise QRCalibrationError("QR error-correction level must be one of L, M, Q, or H")
    for name in ("module_size", "quiet_zone", "right_offset", "bottom_offset"):
        value = getattr(parameters, name)
        if type(value) is not int:
            raise QRCalibrationError(f"QR {name.replace('_', ' ')} must be an integer")
    if parameters.module_size <= 0:
        raise QRCalibrationError("QR module size must be a positive integer")
    if parameters.quiet_zone < 0:
        raise QRCalibrationError("QR quiet-zone width must be a nonnegative integer")
    if parameters.right_offset < 0 or parameters.bottom_offset < 0:
        raise QRCalibrationError("QR right and bottom offsets must be nonnegative integers")


def create_qr_calibration_image(
    parameters: QRCalibrationParameters = QRCalibrationParameters(),
) -> QRCalibrationImage:
    """Create the complete QR calibration canvas and its resolved pixel geometry."""
    validate_qr_calibration_parameters(parameters)
    code = qrcode.QRCode(
        version=None,
        error_correction=_ERROR_CORRECTION[parameters.error_correction],
        box_size=1,
        border=0,
    )
    try:
        code.add_data(parameters.payload.encode("utf-8"), optimize=0)
        code.make(fit=True)
    except (DataOverflowError, ValueError) as error:
        raise QRCalibrationError(
            f"QR payload is too large for error-correction level {parameters.error_correction}; "
            "shorten the payload or choose a lower error-correction level"
        ) from error

    symbol_modules = code.modules_count
    quiet_zone_pixels = parameters.quiet_zone * parameters.module_size
    footprint_side = (symbol_modules + 2 * parameters.quiet_zone) * parameters.module_size
    footprint_size = (footprint_side, footprint_side)
    available_size = (_CANVAS_SIZE[0] - parameters.right_offset, _CANVAS_SIZE[1] - parameters.bottom_offset)
    if footprint_size[0] > available_size[0] or footprint_size[1] > available_size[1]:
        raise QRCalibrationError(
            f"QR footprint is {footprint_size[0]} x {footprint_size[1]} pixels, but only "
            f"{available_size[0]} x {available_size[1]} pixels are available after the requested offsets "
            f"on the {_CANVAS_SIZE[0]} x {_CANVAS_SIZE[1]} canvas; reduce the module size or quiet zone, "
            "shorten the payload, or reduce the offsets"
        )

    left = _CANVAS_SIZE[0] - parameters.right_offset - footprint_side
    top = _CANVAS_SIZE[1] - parameters.bottom_offset - footprint_side
    bounds = (left, top, left + footprint_side - 1, top + footprint_side - 1)
    geometry = QRCalibrationGeometry(
        version=code.version,
        symbol_modules=symbol_modules,
        module_size=parameters.module_size,
        quiet_zone=parameters.quiet_zone,
        quiet_zone_pixels=quiet_zone_pixels,
        footprint_size=footprint_size,
        right_offset=parameters.right_offset,
        bottom_offset=parameters.bottom_offset,
        bounds=bounds,
        image_size=_CANVAS_SIZE,
    )

    image = Image.new("RGB", _CANVAS_SIZE, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    symbol_left = left + quiet_zone_pixels
    symbol_top = top + quiet_zone_pixels
    for row_index, row in enumerate(code.modules):
        y0 = symbol_top + row_index * parameters.module_size
        for column_index, dark in enumerate(row):
            if dark:
                x0 = symbol_left + column_index * parameters.module_size
                draw.rectangle(
                    (
                        x0,
                        y0,
                        x0 + parameters.module_size - 1,
                        y0 + parameters.module_size - 1,
                    ),
                    fill=(0, 0, 0),
                )
    return QRCalibrationImage(image, geometry)


__all__ = [
    "QRCalibrationError",
    "QRCalibrationGeometry",
    "QRCalibrationImage",
    "QRCalibrationParameters",
    "create_qr_calibration_image",
    "validate_qr_calibration_parameters",
]

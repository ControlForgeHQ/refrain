"""Reusable hardware-independent QR generation and image composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q
from qrcode.exceptions import DataOverflowError

from .geometry import round_half_up, working_canvas_for_output

REPOSITORY_URL = "https://github.com/ControlForgeHQ/refrain"
QR_ALLOCATION_SIZE = 246
QR_FOOTPRINT_MODULES = 41
_ERROR_CORRECTION = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}


class QRCodeGenerationError(ValueError):
    """Raised when QR parameters cannot produce a fitting symbol."""


class QRCodePlacementError(ValueError):
    """Raised when production QR placement cannot be resolved."""


@dataclass(frozen=True)
class QRCodeParameters:
    url: str | None
    version: int | None
    error_correction: str
    module_size: int
    quiet_zone: int
    right_offset: int
    bottom_offset: int


@dataclass(frozen=True)
class QRCodeGeometry:
    version: int
    symbol_modules: int
    module_size: int
    quiet_zone: int
    quiet_zone_pixels: int
    footprint_size: tuple[int, int]
    right_offset: int | None
    bottom_offset: int | None
    bounds: tuple[int, int, int, int]
    image_size: tuple[int, int]
    allocation_bounds: tuple[int, int, int, int] | None = None
    working_bounds: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class QRCodePlacement:
    """Resolved production QR allocation and integer-pixel footprint."""

    working_bounds: tuple[int, int, int, int]
    allocation_bounds: tuple[int, int, int, int]
    allocation_size: tuple[int, int]
    module_size: int
    footprint_size: tuple[int, int]
    bounds: tuple[int, int, int, int]
    image_size: tuple[int, int]


@dataclass(frozen=True)
class QRCodeImage:
    image: Image.Image
    geometry: QRCodeGeometry


PRODUCTION_QR_PARAMETERS = QRCodeParameters(
    url=REPOSITORY_URL,
    version=4,
    error_correction="M",
    module_size=3,
    quiet_zone=4,
    right_offset=40,
    bottom_offset=40,
)


def resolve_qr_placement(
    output_size: tuple[int, int],
    positioning: Mapping[str, object] | None = None,
) -> QRCodePlacement:
    """Resolve the fixed working-canvas allocation and its fitting QR footprint."""
    metadata = {} if positioning is None else positioning
    if not isinstance(metadata, Mapping):
        raise QRCodePlacementError("QR positioning metadata must be a mapping")

    allowed = {
        "qr_from_left",
        "qr_from_right",
        "qr_from_top",
        "qr_from_bottom",
        "qr_centered",
    }
    if any(key not in allowed for key in metadata):
        raise QRCodePlacementError("QR positioning metadata contains an unsupported field")
    for key in allowed - {"qr_centered"}:
        if key in metadata and (type(metadata[key]) is not int or metadata[key] < 0):
            raise QRCodePlacementError(f"{key} must be a nonnegative integer working-canvas pixel offset")

    centered = metadata.get("qr_centered")
    if "qr_centered" in metadata and (not isinstance(centered, str) or centered not in {"horizontal", "vertical"}):
        raise QRCodePlacementError("qr_centered must be the scalar string 'horizontal' or 'vertical'")

    working_size, _ = working_canvas_for_output(output_size)
    working_width, working_height = working_size
    horizontal = [key for key in ("qr_from_left", "qr_from_right") if key in metadata]
    if centered == "horizontal":
        horizontal.append("qr_centered")
    if len(horizontal) > 1:
        raise QRCodePlacementError("QR horizontal positioning methods conflict; specify exactly one method")

    vertical = [key for key in ("qr_from_top", "qr_from_bottom") if key in metadata]
    if centered == "vertical":
        vertical.append("qr_centered")
    if len(vertical) > 1:
        raise QRCodePlacementError("QR vertical positioning methods conflict; specify exactly one method")

    if not horizontal:
        horizontal = ["qr_from_right"]
    if not vertical:
        vertical = ["qr_from_bottom"]

    if horizontal[0] == "qr_from_left":
        left = metadata["qr_from_left"]
    elif horizontal[0] == "qr_from_right":
        left = working_width - QR_ALLOCATION_SIZE - metadata.get("qr_from_right", 20)
    else:
        left = round_half_up(working_width - QR_ALLOCATION_SIZE, 2)

    if vertical[0] == "qr_from_top":
        top = metadata["qr_from_top"]
    elif vertical[0] == "qr_from_bottom":
        top = working_height - QR_ALLOCATION_SIZE - metadata.get("qr_from_bottom", 20)
    else:
        top = round_half_up(working_height - QR_ALLOCATION_SIZE, 2)

    working_bounds = (left, top, left + QR_ALLOCATION_SIZE, top + QR_ALLOCATION_SIZE)
    if (
        working_bounds[0] < 0
        or working_bounds[1] < 0
        or working_bounds[2] > working_width
        or working_bounds[3] > working_height
    ):
        raise QRCodePlacementError(
            f"the 246 x 246 QR allocation at working-canvas bounds {working_bounds} extends outside "
            f"the {working_width} x {working_height} working canvas; reduce the configured offset"
        )

    output_width, output_height = output_size
    allocation_bounds = (
        round_half_up(working_bounds[0] * output_width, working_width),
        round_half_up(working_bounds[1] * output_height, working_height),
        round_half_up(working_bounds[2] * output_width, working_width),
        round_half_up(working_bounds[3] * output_height, working_height),
    )
    allocation_width = allocation_bounds[2] - allocation_bounds[0]
    allocation_height = allocation_bounds[3] - allocation_bounds[1]
    module_size = min(allocation_width, allocation_height) // QR_FOOTPRINT_MODULES
    if module_size < 1:
        raise QRCodePlacementError(
            f"the 246 x 246 working-canvas QR allocation maps to only {allocation_width} x "
            f"{allocation_height} output pixels, which cannot fit the complete 41-module QR footprint "
            "at one pixel per module; use a larger output resolution"
        )

    footprint_side = QR_FOOTPRINT_MODULES * module_size
    left = allocation_bounds[0] + round_half_up(allocation_width - footprint_side, 2)
    top = allocation_bounds[1] + round_half_up(allocation_height - footprint_side, 2)
    bounds = (left, top, left + footprint_side - 1, top + footprint_side - 1)
    return QRCodePlacement(
        working_bounds=working_bounds,
        allocation_bounds=allocation_bounds,
        allocation_size=(allocation_width, allocation_height),
        module_size=module_size,
        footprint_size=(footprint_side, footprint_side),
        bounds=bounds,
        image_size=output_size,
    )


def qr_parameters_to_metadata(parameters: QRCodeParameters) -> dict[str, object]:
    validate_qr_parameters(parameters)
    return {
        "url": REPOSITORY_URL if parameters.url is None else parameters.url,
        "version": parameters.version,
        "error_correction": parameters.error_correction,
        "module_size": parameters.module_size,
        "quiet_zone": parameters.quiet_zone,
        "right_offset": parameters.right_offset,
        "bottom_offset": parameters.bottom_offset,
    }


def qr_parameters_from_metadata(value: object) -> QRCodeParameters:
    if not isinstance(value, Mapping):
        raise QRCodeGenerationError("snapshot.presentation_metadata.qr_code must be a mapping")
    fields = {
        "url",
        "version",
        "error_correction",
        "module_size",
        "quiet_zone",
        "right_offset",
        "bottom_offset",
    }
    if set(value) != fields:
        raise QRCodeGenerationError("snapshot.presentation_metadata.qr_code must contain exactly the QR parameters")
    if not isinstance(value["url"], str) or not value["url"]:
        raise QRCodeGenerationError("snapshot QR URL must be a nonempty resolved string")
    if type(value["version"]) is not int or not 1 <= value["version"] <= 40:
        raise QRCodeGenerationError("snapshot QR version must be an integer from 1 through 40")
    parameters = QRCodeParameters(
        url=value["url"],
        version=value["version"],
        error_correction=value["error_correction"],
        module_size=value["module_size"],
        quiet_zone=value["quiet_zone"],
        right_offset=value["right_offset"],
        bottom_offset=value["bottom_offset"],
    )
    validate_qr_parameters(parameters)
    return parameters


def validate_qr_parameters(parameters: QRCodeParameters) -> None:
    if not isinstance(parameters, QRCodeParameters):
        raise QRCodeGenerationError("parameters must be a QRCodeParameters value")
    if parameters.url is not None and (not isinstance(parameters.url, str) or not parameters.url):
        raise QRCodeGenerationError("QR URL must be a nonempty string when supplied")
    try:
        (REPOSITORY_URL if parameters.url is None else parameters.url).encode("utf-8")
    except UnicodeEncodeError as error:
        raise QRCodeGenerationError("QR URL must be representable as UTF-8 text") from error
    if not isinstance(parameters.error_correction, str) or parameters.error_correction not in _ERROR_CORRECTION:
        raise QRCodeGenerationError("QR error-correction level must be one of L, M, Q, or H")
    if parameters.version is not None and (type(parameters.version) is not int or not 1 <= parameters.version <= 40):
        raise QRCodeGenerationError("QR version must be 'auto' or an integer from 1 through 40")
    for name in ("module_size", "quiet_zone", "right_offset", "bottom_offset"):
        if type(getattr(parameters, name)) is not int:
            raise QRCodeGenerationError(f"QR {name.replace('_', ' ')} must be an integer")
    if parameters.module_size <= 0:
        raise QRCodeGenerationError("QR module size must be a positive integer")
    if parameters.quiet_zone < 0:
        raise QRCodeGenerationError("QR quiet-zone width must be a nonnegative integer")
    if parameters.right_offset < 0 or parameters.bottom_offset < 0:
        raise QRCodeGenerationError("QR right and bottom offsets must be nonnegative integers")


def render_qr_code(
    parameters: QRCodeParameters,
    image_size: tuple[int, int],
    placement: QRCodePlacement | None = None,
) -> QRCodeImage:
    """Encode and rasterize a complete QR footprint for a specific destination size."""
    validate_qr_parameters(parameters)
    if (
        not isinstance(image_size, tuple)
        or len(image_size) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in image_size)
    ):
        raise QRCodeGenerationError("destination image dimensions must be two positive integers")
    code = qrcode.QRCode(
        version=parameters.version,
        error_correction=_ERROR_CORRECTION[parameters.error_correction],
        box_size=1,
        border=0,
    )
    payload = REPOSITORY_URL if parameters.url is None else parameters.url
    try:
        code.add_data(payload.encode("utf-8"), optimize=0)
        code.make(fit=parameters.version is None)
    except DataOverflowError as error:
        if parameters.version is not None:
            raise QRCodeGenerationError(
                f"QR payload exceeds available capacity for requested version {parameters.version} "
                f"at error-correction level {parameters.error_correction}; increase the version, "
                "shorten the payload, or reduce the error-correction level"
            ) from error
        raise QRCodeGenerationError(
            f"QR payload is too large for error-correction level {parameters.error_correction}; "
            "shorten the payload or choose a lower error-correction level"
        ) from error
    except ValueError as error:
        raise QRCodeGenerationError(
            f"QR payload is too large for error-correction level {parameters.error_correction}; "
            "shorten the payload or choose a lower error-correction level"
        ) from error

    width, height = image_size
    symbol_modules = code.modules_count
    module_size = parameters.module_size
    if placement is not None:
        if not isinstance(placement, QRCodePlacement) or placement.image_size != image_size:
            raise QRCodeGenerationError("QR placement does not match the destination image dimensions")
        module_size = placement.module_size
    quiet_zone_pixels = parameters.quiet_zone * module_size
    footprint_side = (symbol_modules + 2 * parameters.quiet_zone) * module_size
    footprint_size = (footprint_side, footprint_side)
    if placement is None:
        available_size = (width - parameters.right_offset, height - parameters.bottom_offset)
        if footprint_side > available_size[0] or footprint_side > available_size[1]:
            raise QRCodeGenerationError(
                f"QR footprint is {footprint_side} x {footprint_side} pixels, but only "
                f"{available_size[0]} x {available_size[1]} pixels are available after the requested offsets "
                f"on the {width} x {height} destination image; reduce the module size or quiet zone, "
                "shorten the payload, or reduce the offsets"
            )
        left = width - parameters.right_offset - footprint_side
        top = height - parameters.bottom_offset - footprint_side
        bounds = (left, top, left + footprint_side - 1, top + footprint_side - 1)
        allocation_bounds = None
        working_bounds = None
        right_offset: int | None = parameters.right_offset
        bottom_offset: int | None = parameters.bottom_offset
    else:
        if footprint_size != placement.footprint_size:
            raise QRCodeGenerationError("QR parameters do not match the resolved placement footprint")
        bounds = placement.bounds
        allocation_bounds = placement.allocation_bounds
        working_bounds = placement.working_bounds
        left, top, right, bottom = bounds
        allocation_left, allocation_top, allocation_right, allocation_bottom = allocation_bounds
        if left < allocation_left or top < allocation_top or right >= allocation_right or bottom >= allocation_bottom:
            raise QRCodeGenerationError("resolved QR footprint lies outside its allocation")
        right_offset = None
        bottom_offset = None
    geometry = QRCodeGeometry(
        version=code.version,
        symbol_modules=symbol_modules,
        module_size=module_size,
        quiet_zone=parameters.quiet_zone,
        quiet_zone_pixels=quiet_zone_pixels,
        footprint_size=footprint_size,
        right_offset=right_offset,
        bottom_offset=bottom_offset,
        bounds=bounds,
        image_size=image_size,
        allocation_bounds=allocation_bounds,
        working_bounds=working_bounds,
    )

    image = Image.new("RGB", footprint_size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for row_index, row in enumerate(code.modules):
        y0 = quiet_zone_pixels + row_index * module_size
        for column_index, dark in enumerate(row):
            if dark:
                x0 = quiet_zone_pixels + column_index * module_size
                draw.rectangle(
                    (
                        x0,
                        y0,
                        x0 + module_size - 1,
                        y0 + module_size - 1,
                    ),
                    fill=(0, 0, 0),
                )
    return QRCodeImage(image, geometry)


def composite_qr_code(destination: Image.Image, qr_code: QRCodeImage) -> None:
    """Composite the opaque QR footprint over the destination without resampling."""
    if not isinstance(destination, Image.Image) or destination.mode != "RGB":
        raise QRCodeGenerationError("QR destination must be an RGB Pillow image")
    if not isinstance(qr_code, QRCodeImage) or destination.size != qr_code.geometry.image_size:
        raise QRCodeGenerationError("QR geometry does not match the destination image dimensions")
    if qr_code.image.mode != "RGB" or qr_code.image.size != qr_code.geometry.footprint_size:
        raise QRCodeGenerationError("QR footprint image does not match its resolved geometry")
    left, top, _, _ = qr_code.geometry.bounds
    destination.paste(qr_code.image, (left, top))


__all__ = [
    "PRODUCTION_QR_PARAMETERS",
    "QR_ALLOCATION_SIZE",
    "QRCodePlacement",
    "QRCodePlacementError",
    "QRCodeGenerationError",
    "QRCodeGeometry",
    "QRCodeImage",
    "QRCodeParameters",
    "REPOSITORY_URL",
    "composite_qr_code",
    "qr_parameters_from_metadata",
    "qr_parameters_to_metadata",
    "render_qr_code",
    "resolve_qr_placement",
    "validate_qr_parameters",
]

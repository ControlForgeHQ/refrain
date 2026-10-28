"""Linux SPI and GPIO transport for the Waveshare 13.3-inch E panel."""

from __future__ import annotations

import importlib
import time
from collections.abc import Sequence
from typing import Any

SPI_DEVICE = (0, 0)
SPI_SPEED_HZ = 1_000_000
SPI_CHUNK_SIZE = 4096
GPIO_CHIP = "/dev/gpiochip0"

EPD_CS_M_PIN = 8
EPD_CS_S_PIN = 7
EPD_DC_PIN = 25
EPD_RST_PIN = 17
EPD_BUSY_PIN = 24
EPD_PWR_PIN = 18

_OUTPUT_PINS = (EPD_CS_M_PIN, EPD_CS_S_PIN, EPD_RST_PIN, EPD_PWR_PIN)
_spi: Any = None
_lines: Any = None
_value_type: Any = None
_state = "inactive"
_pending = bytearray()


def _require_active() -> tuple[Any, Any, Any]:
    if _state != "active" or _spi is None or _lines is None:
        raise RuntimeError(f"Linux SPI/GPIO transport is {_state}; refusing hardware access")
    return _spi, _lines, _value_type


def _set_line(pin: int, value: int) -> None:
    _spi_device, lines, value_type = _require_active()
    try:
        lines.set_value(pin, value_type.ACTIVE if value else value_type.INACTIVE)
    except Exception:
        _poison()
        raise


def _poison() -> None:
    global _state
    _state = "poisoned"


def _flush_pending() -> None:
    spi, _lines_device, _value_enum = _require_active()
    if not _pending:
        return
    payload = bytes(_pending)
    try:
        spi.writebytes2(payload)
    except Exception:
        _poison()
        raise
    _pending.clear()


def digital_write(pin: int, value: int) -> None:
    """Set one controller control signal, flushing buffered data first."""
    _flush_pending()
    _set_line(pin, value)


def digital_read(pin: int) -> int:
    """Read a GPIO input as zero or one."""
    _spi_device, lines, value_type = _require_active()
    try:
        return int(lines.get_value(pin) == value_type.ACTIVE)
    except Exception:
        _poison()
        raise


def spi_writebyte(value: int) -> None:
    """Transmit one command or data byte over hardware SPI."""
    _flush_pending()
    spi, _lines_device, _value_enum = _require_active()
    try:
        spi.writebytes2(bytes((value,)))
    except Exception:
        _poison()
        raise


def spi_writebyte2(buffer: Sequence[int], length: int) -> None:
    """Buffer image data and transmit bounded SPI transfers before control changes."""
    if length < 0 or length > len(buffer):
        raise ValueError(f"invalid SPI buffer length {length}")
    _require_active()
    try:
        view = memoryview(buffer).cast("B")
    except TypeError:
        view = None

    offset = 0
    while offset < length:
        available = SPI_CHUNK_SIZE - len(_pending)
        end = min(offset + available, length)
        if view is None:
            _pending.extend(buffer[offset:end])
        else:
            _pending.extend(view[offset:end])
        offset = end
        if len(_pending) == SPI_CHUNK_SIZE:
            _flush_pending()


def delay_ms(milliseconds: int) -> None:
    time.sleep(milliseconds / 1000)


def module_init() -> None:
    """Acquire SPI/GPIO resources and perform the board power-on sequence."""
    global _lines, _spi, _state, _value_type

    if _state != "inactive":
        raise RuntimeError(f"Linux SPI/GPIO transport is {_state}; refusing to initialize it again")

    try:
        gpiod = importlib.import_module("gpiod")
        line = importlib.import_module("gpiod.line")
        value_type = line.Value
        line_settings = {
            pin: gpiod.LineSettings(
                direction=line.Direction.OUTPUT,
                output_value=value_type.ACTIVE,
            )
            for pin in _OUTPUT_PINS
        }
        line_settings[EPD_BUSY_PIN] = gpiod.LineSettings(direction=line.Direction.INPUT)
        lines = gpiod.request_lines(
            GPIO_CHIP,
            consumer="refrain-waveshare-13in3-e",
            config=line_settings,
        )
        spi = importlib.import_module("spidev").SpiDev()
        spi.open(*SPI_DEVICE)
        spi.mode = 0
        spi.bits_per_word = 8
        spi.lsbfirst = False
        spi.max_speed_hz = SPI_SPEED_HZ
        spi.no_cs = True
    except Exception:
        _lines = locals().get("lines")
        _spi = locals().get("spi")
        _value_type = locals().get("value_type")
        if _lines is not None or _spi is not None:
            _state = "active"
            try:
                module_exit()
            except Exception:
                _poison()
        raise

    _lines = lines
    _spi = spi
    _value_type = value_type
    _state = "active"
    try:
        digital_write(EPD_PWR_PIN, 1)
        delay_ms(30)
        digital_write(EPD_PWR_PIN, 0)
        delay_ms(30)
        digital_write(EPD_PWR_PIN, 1)
        delay_ms(30)
    except Exception:
        _poison()
        raise


def module_exit() -> None:
    """Release acquired resources, attempting every cleanup operation."""
    global _lines, _pending, _spi, _state, _value_type

    if _state == "inactive":
        return

    was_poisoned = _state == "poisoned"
    errors: list[Exception] = []
    _pending.clear()
    if _lines is not None:
        try:
            _lines.set_value(EPD_CS_M_PIN, _value_type.ACTIVE)
        except Exception as error:
            errors.append(error)
        try:
            _lines.set_value(EPD_CS_S_PIN, _value_type.ACTIVE)
        except Exception as error:
            errors.append(error)
    if _spi is not None:
        try:
            _spi.close()
        except Exception as error:
            errors.append(error)
        else:
            _spi = None
    if _lines is not None:
        try:
            _lines.release()
        except Exception as error:
            errors.append(error)
        else:
            _lines = None
    if _lines is None:
        _value_type = None
    if errors or was_poisoned:
        _poison()
    else:
        _state = "inactive"
    if errors:
        raise RuntimeError(f"could not clean up Linux SPI/GPIO resources: {errors[0]}") from errors[0]


def is_initialized() -> bool:
    return _spi is not None or _lines is not None


def is_poisoned() -> bool:
    return _state == "poisoned"

from __future__ import annotations

from enum import Enum, IntEnum
from types import ModuleType
from typing import Any

import pytest

import refrain.display.waveshare_transport as transport


class Direction(Enum):
    INPUT = "input"
    OUTPUT = "output"


class Value(IntEnum):
    INACTIVE = 0
    ACTIVE = 1


class FakeLines:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.values: dict[int, Value] = {}

    def set_value(self, pin: int, value: Value) -> None:
        self.calls.append(("set", pin, value))
        self.values[pin] = value

    def get_value(self, pin: int) -> Value:
        self.calls.append(("get", pin))
        return self.values.get(pin, Value.INACTIVE)

    def release(self) -> None:
        self.calls.append(("release",))


class FakeSpi:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.writes: list[bytes] = []
        self.fail_writes = False

    def open(self, bus: int, device: int) -> None:
        self.calls.append(("open", bus, device))

    def writebytes2(self, buffer: bytes) -> None:
        self.calls.append(("write", len(buffer)))
        if self.fail_writes:
            raise OSError("SPI transfer failed")
        self.writes.append(bytes(buffer))

    def close(self) -> None:
        self.calls.append(("close",))


class FakeGpiod:
    def __init__(self, lines: FakeLines) -> None:
        self.lines = lines
        self.settings: dict[int, Any] | None = None

    def LineSettings(self, **kwargs: Any) -> dict[str, Any]:
        return kwargs

    def request_lines(self, chip: str, *, consumer: str, config: dict[int, Any]) -> FakeLines:
        assert chip == transport.GPIO_CHIP
        assert consumer == "refrain-waveshare-13in3-e"
        self.settings = config
        return self.lines


@pytest.fixture
def fake_hardware(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeSpi, FakeLines, FakeGpiod]:
    lines = FakeLines()
    spi = FakeSpi()
    gpiod = FakeGpiod(lines)
    line_module = ModuleType("gpiod.line")
    line_module.Direction = Direction  # type: ignore[attr-defined]
    line_module.Value = Value  # type: ignore[attr-defined]
    gpiod_module = ModuleType("gpiod")
    gpiod_module.LineSettings = gpiod.LineSettings  # type: ignore[attr-defined]
    gpiod_module.request_lines = gpiod.request_lines  # type: ignore[attr-defined]
    spidev_module = ModuleType("spidev")
    spidev_module.SpiDev = lambda: spi  # type: ignore[attr-defined]
    modules = {"gpiod": gpiod_module, "gpiod.line": line_module, "spidev": spidev_module}
    monkeypatch.setattr(transport.importlib, "import_module", modules.__getitem__)
    monkeypatch.setattr(transport, "_spi", None)
    monkeypatch.setattr(transport, "_lines", None)
    monkeypatch.setattr(transport, "_value_type", None)
    monkeypatch.setattr(transport, "_state", "inactive")
    monkeypatch.setattr(transport, "_pending", bytearray())
    monkeypatch.setattr(transport, "delay_ms", lambda _milliseconds: None)
    return spi, lines, gpiod


def test_initialization_configures_spi_gpio_and_releases_owned_resources(
    fake_hardware: tuple[FakeSpi, FakeLines, FakeGpiod],
) -> None:
    spi, lines, gpiod = fake_hardware
    transport.module_init()

    assert spi.calls == [("open", 0, 0)]
    assert spi.mode == 0
    assert spi.bits_per_word == 8
    assert spi.lsbfirst is False
    assert spi.max_speed_hz == 1_000_000
    assert spi.no_cs is True
    assert gpiod.settings is not None
    assert set(gpiod.settings) == {
        transport.EPD_CS_M_PIN,
        transport.EPD_CS_S_PIN,
        transport.EPD_RST_PIN,
        transport.EPD_BUSY_PIN,
        transport.EPD_PWR_PIN,
    }
    assert gpiod.settings[transport.EPD_BUSY_PIN]["direction"] is Direction.INPUT
    assert gpiod.settings[transport.EPD_CS_M_PIN]["output_value"] is Value.ACTIVE
    lines.values[transport.EPD_BUSY_PIN] = Value.ACTIVE
    assert transport.digital_read(transport.EPD_BUSY_PIN) == 1
    lines.values[transport.EPD_BUSY_PIN] = Value.INACTIVE
    assert transport.digital_read(transport.EPD_BUSY_PIN) == 0
    assert [call for call in lines.calls if call[0] == "set"] == [
        ("set", transport.EPD_PWR_PIN, Value.ACTIVE),
        ("set", transport.EPD_PWR_PIN, Value.INACTIVE),
        ("set", transport.EPD_PWR_PIN, Value.ACTIVE),
    ]
    assert transport.is_initialized()

    transport.module_exit()
    transport.module_exit()

    assert spi.calls[-1] == ("close",)
    assert lines.calls[-1] == ("release",)
    assert not transport.is_initialized()
    assert not transport.is_poisoned()


def test_large_image_writes_are_chunked_and_flushed_before_chip_select_release(
    fake_hardware: tuple[FakeSpi, FakeLines, FakeGpiod],
) -> None:
    spi, _lines, _gpiod = fake_hardware
    transport.module_init()
    payload = bytes(index % 256 for index in range(9000))

    transport.digital_write(transport.EPD_CS_M_PIN, 0)
    transport.spi_writebyte(0x10)
    transport.spi_writebyte2(payload, len(payload))

    assert spi.writes == [b"\x10", payload[:4096], payload[4096:8192]]
    transport.digital_write(transport.EPD_CS_M_PIN, 1)

    assert spi.writes == [b"\x10", payload[:4096], payload[4096:8192], payload[8192:]]
    transport.module_exit()


def test_spi_failure_poisoning_blocks_follow_up_io_but_still_releases_resources(
    fake_hardware: tuple[FakeSpi, FakeLines, FakeGpiod],
) -> None:
    spi, lines, _gpiod = fake_hardware
    transport.module_init()
    spi.fail_writes = True

    with pytest.raises(OSError, match="SPI transfer failed"):
        transport.spi_writebyte(0x10)
    assert transport.is_poisoned()
    with pytest.raises(RuntimeError, match="poisoned"):
        transport.digital_read(transport.EPD_BUSY_PIN)

    transport.module_exit()

    assert ("close",) in spi.calls
    assert ("release",) in lines.calls
    assert not transport.is_initialized()
    assert transport.is_poisoned()


def test_partial_initialization_releases_gpio_and_can_be_retried(
    fake_hardware: tuple[FakeSpi, FakeLines, FakeGpiod],
) -> None:
    spi, lines, _gpiod = fake_hardware
    original_open = spi.open
    attempts = [0]

    def fail_first_open(bus: int, device: int) -> None:
        attempts[0] += 1
        if attempts[0] == 1:
            raise OSError("SPI device unavailable")
        original_open(bus, device)

    spi.open = fail_first_open  # type: ignore[method-assign]
    with pytest.raises(OSError, match="SPI device unavailable"):
        transport.module_init()
    assert lines.calls[-1] == ("release",)
    assert not transport.is_initialized()
    assert not transport.is_poisoned()

    transport.module_init()
    transport.module_exit()
    assert attempts[0] == 2


def test_cleanup_attempts_both_interfaces_and_preserves_poison(
    fake_hardware: tuple[FakeSpi, FakeLines, FakeGpiod],
) -> None:
    spi, lines, _gpiod = fake_hardware
    transport.module_init()
    close_attempts = [0]
    release_attempts = [0]

    def fail_close() -> None:
        close_attempts[0] += 1
        if close_attempts[0] == 1:
            raise OSError("SPI close failed")
        spi.calls.append(("close",))

    def fail_release() -> None:
        release_attempts[0] += 1
        lines.calls.append(("release",))
        if release_attempts[0] == 1:
            raise OSError("GPIO release failed")

    spi.close = fail_close  # type: ignore[method-assign]
    lines.release = fail_release  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="SPI close failed"):
        transport.module_exit()
    assert transport.is_initialized()

    transport.module_exit()

    assert release_attempts == [2]
    assert close_attempts == [2]
    assert not transport.is_initialized()
    assert transport.is_poisoned()

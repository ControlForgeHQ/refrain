from __future__ import annotations

from typing import Any

import pytest

from refrain.display.vendor.waveshare import epd13in3E, epdconfig


def test_display_preserves_controller_regions_and_selects_each_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(epdconfig, "digital_write", lambda pin, value: calls.append(("gpio", pin, value)))
    monkeypatch.setattr(epdconfig, "spi_writebyte", lambda value: calls.append(("command", value)))
    monkeypatch.setattr(
        epdconfig,
        "spi_writebyte2",
        lambda buffer, length: calls.append(("data", bytes(buffer[:length]))),
    )
    epd = epd13in3E.EPD()
    epd.TurnOnDisplay = lambda: None
    image = [index % 256 for index in range(epd.width * epd.height // 2)]

    epd.display(image)

    row_bytes = epd.width // 2
    panel_bytes = epd.width // 4
    expected_master = b"".join(
        bytes(image[row * row_bytes : row * row_bytes + panel_bytes]) for row in range(epd.height)
    )
    expected_secondary = b"".join(
        bytes(image[row * row_bytes + panel_bytes : (row + 1) * row_bytes]) for row in range(epd.height)
    )
    assert calls == [
        ("gpio", epd.EPD_CS_M_PIN, 0),
        ("command", 0x10),
        ("data", expected_master),
        ("gpio", epd.EPD_CS_M_PIN, 1),
        ("gpio", epd.EPD_CS_S_PIN, 1),
        ("gpio", epd.EPD_CS_S_PIN, 0),
        ("command", 0x10),
        ("data", expected_secondary),
        ("gpio", epd.EPD_CS_M_PIN, 1),
        ("gpio", epd.EPD_CS_S_PIN, 1),
    ]


def test_driver_can_select_both_controllers_simultaneously(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(epdconfig, "digital_write", lambda pin, value: calls.append((pin, value)))

    epd13in3E.EPD().CS_ALL(0)

    assert calls == [(epdconfig.EPD_CS_M_PIN, 0), (epdconfig.EPD_CS_S_PIN, 0)]


def test_busy_polling_uses_a_bounded_monotonic_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    delays: list[int] = []
    monkeypatch.setattr(epdconfig, "digital_read", lambda _pin: 0)

    def delay(milliseconds: int) -> None:
        delays.append(milliseconds)
        clock[0] += milliseconds / 1000

    monkeypatch.setattr(epdconfig, "delay_ms", delay)
    monkeypatch.setattr(epd13in3E.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(epd13in3E, "BUSY_TIMEOUT_SECONDS", 0.01)
    epd = epd13in3E.EPD()

    with pytest.raises(TimeoutError, match="BUSY signal did not clear"):
        epd.ReadBusyH()

    assert delays == [5, 5]

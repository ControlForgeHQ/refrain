from __future__ import annotations

from importlib.resources import files
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

import refrain.display.waveshare as waveshare_module
from refrain.display import (
    DisplayBackend,
    DisplayBackendCloseError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
    create_display_backend,
)

_DEFAULT = object()


class SimulatedDriver:
    def __init__(self, outcomes: dict[str, list[Any]] | None = None) -> None:
        self.calls: list[str] = []
        self.images: list[Image.Image] = []
        self.buffer = ["simulated image buffer"]
        self.outcomes = outcomes or {}

    def _call(self, name: str, default: Any = None) -> Any:
        self.calls.append(name)
        outcome = self.outcomes.get(name, [])
        result = outcome.pop(0) if outcome else _DEFAULT
        if isinstance(result, Exception):
            raise result
        return default if result is _DEFAULT else result

    def Init(self) -> Any:
        return self._call("Init")

    def getbuffer(self, image: Image.Image) -> Any:
        self.images.append(image)
        image.putpixel((0, 0), (0, 0, 0))
        return self._call("getbuffer", self.buffer)

    def display(self, buffer: Any) -> Any:
        assert buffer is self.buffer
        return self._call("display")

    def sleep(self) -> Any:
        return self._call("sleep")


def install_simulated_driver(monkeypatch: pytest.MonkeyPatch, driver: SimulatedDriver) -> None:
    module = ModuleType("refrain.display.vendor.waveshare.epd13in3E")
    module.EPD = lambda: driver  # type: ignore[attr-defined]
    monkeypatch.setattr(waveshare_module, "import_module", lambda *_args, **_kwargs: module)


def test_factory_constructs_waveshare_backend_and_updates_both_orientations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = SimulatedDriver()
    install_simulated_driver(monkeypatch, driver)

    backend = create_display_backend("waveshare-13in3-e")
    assert isinstance(backend, DisplayBackend)
    images = [Image.new("RGB", (1200, 1600), "red"), Image.new("RGB", (1600, 1200), "blue")]
    original_pixels = [image.tobytes() for image in images]

    for image in images:
        backend.update(image)

    assert driver.calls == ["Init", "getbuffer", "display", "sleep"] * 2
    assert len(driver.images) == 2
    assert all(driver_image is not original for driver_image, original in zip(driver.images, images, strict=True))
    assert [image.tobytes() for image in images] == original_pixels
    backend.close()
    assert driver.calls == ["Init", "getbuffer", "display", "sleep"] * 2


def test_invalid_images_are_rejected_before_hardware_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = SimulatedDriver()
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(DisplayBackendUpdateError, match="Pillow Image.Image"):
        backend.update(object())  # type: ignore[arg-type]
    with pytest.raises(DisplayBackendUpdateError, match="1200 x 1600 or 1600 x 1200"):
        backend.update(Image.new("RGB", (1024, 768)))

    assert driver.calls == []


def test_driver_loading_failure_has_actionable_initialization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("native library unavailable")

    monkeypatch.setattr(waveshare_module, "import_module", fail_import)

    with pytest.raises(DisplayBackendInitializationError, match="bundled native library.*native library unavailable"):
        create_display_backend("waveshare-13in3-e")


@pytest.mark.parametrize(
    ("operation", "error_type", "expected_calls"),
    [
        ("Init", DisplayBackendInitializationError, ["Init", "sleep"]),
        ("getbuffer", DisplayBackendUpdateError, ["Init", "getbuffer", "sleep"]),
        ("display", DisplayBackendUpdateError, ["Init", "getbuffer", "display", "sleep"]),
    ],
)
def test_driver_exceptions_are_translated_and_sleep_is_attempted(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error_type: type[Exception],
    expected_calls: list[str],
) -> None:
    driver = SimulatedDriver({operation: [RuntimeError("simulated failure")]})
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(error_type, match="simulated failure"):
        backend.update(Image.new("RGB", (1200, 1600)))

    assert driver.calls == expected_calls


@pytest.mark.parametrize(
    ("operation", "error_type", "expected_calls"),
    [
        ("Init", DisplayBackendInitializationError, ["Init", "sleep"]),
        ("getbuffer", DisplayBackendUpdateError, ["Init", "getbuffer", "sleep"]),
        ("display", DisplayBackendUpdateError, ["Init", "getbuffer", "display", "sleep"]),
        ("sleep", DisplayBackendUpdateError, ["Init", "getbuffer", "display", "sleep"]),
    ],
)
def test_false_driver_results_are_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error_type: type[Exception],
    expected_calls: list[str],
) -> None:
    driver = SimulatedDriver({operation: [False]})
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(error_type, match="reported failure"):
        backend.update(Image.new("RGB", (1200, 1600)))

    assert driver.calls == expected_calls


def test_cleanup_failure_does_not_mask_update_failure_and_close_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = SimulatedDriver(
        {
            "getbuffer": [RuntimeError("conversion failed")],
            "sleep": [RuntimeError("cleanup failed"), RuntimeError("close failed"), None],
        }
    )
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(DisplayBackendUpdateError, match="conversion failed"):
        backend.update(Image.new("RGB", (1200, 1600)))
    with pytest.raises(DisplayBackendCloseError, match="close failed"):
        backend.close()

    backend.close()
    backend.close()
    assert driver.calls == ["Init", "getbuffer", "sleep", "sleep", "sleep"]
    with pytest.raises(DisplayBackendUpdateError, match="closed Waveshare display"):
        backend.update(Image.new("RGB", (1200, 1600)))


def test_vendor_native_libraries_are_package_resources() -> None:
    vendor = files("refrain.display.vendor.waveshare")

    for name in (
        "DEV_Config_32_b.so",
        "DEV_Config_32_w.so",
        "DEV_Config_64_b.so",
        "DEV_Config_64_w.so",
    ):
        assert vendor.joinpath(name).is_file()

from __future__ import annotations

import threading
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

import refrain.display.waveshare as waveshare_module
from refrain.display import (
    DisplayBackend,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
    create_display_backend,
)

_DEFAULT = object()


class SimulatedBuffer:
    def __init__(self, length: int) -> None:
        self.length = length

    def __len__(self) -> int:
        return self.length


class SimulatedDriver:
    def __init__(
        self,
        outcomes: dict[str, list[Any]] | None = None,
        hooks: dict[str, Any] | None = None,
        buffer: Any = None,
    ) -> None:
        self.calls: list[str] = []
        self.images: list[Image.Image] = []
        self.buffer = SimulatedBuffer(960_000) if buffer is None else buffer
        self.outcomes = outcomes or {}
        self.hooks = hooks or {}

    def _call(self, name: str, default: Any = None) -> Any:
        self.calls.append(name)
        if name in self.hooks:
            self.hooks[name]()
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

    assert driver.calls == ["getbuffer", "Init", "display", "sleep"] * 2
    assert len(driver.images) == 2
    assert all(driver_image is not original for driver_image, original in zip(driver.images, images, strict=True))
    assert [image.tobytes() for image in images] == original_pixels
    backend.close()
    assert driver.calls == ["getbuffer", "Init", "display", "sleep"] * 2


def test_backend_construction_does_not_require_linux_hardware_modules() -> None:
    backend = create_display_backend("waveshare-13in3-e")

    assert isinstance(backend, DisplayBackend)
    backend.close()


def test_invalid_images_are_rejected_before_hardware_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = SimulatedDriver()
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(DisplayBackendUpdateError, match="Pillow Image.Image"):
        backend.update(object())  # type: ignore[arg-type]
    with pytest.raises(DisplayBackendUpdateError, match="1200 x 1600 or 1600 x 1200"):
        backend.update(Image.new("RGB", (1024, 768)))
    with pytest.raises(DisplayBackendUpdateError, match="mode must be RGB.*transparency"):
        backend.update(Image.new("RGBA", (1200, 1600), (1, 2, 3, 255)))

    assert driver.calls == []


@pytest.mark.parametrize("buffer", [SimulatedBuffer(959_999), SimulatedBuffer(960_001), object()])
def test_invalid_converted_buffers_are_rejected_before_hardware(monkeypatch: pytest.MonkeyPatch, buffer: Any) -> None:
    driver = SimulatedDriver(buffer=buffer)
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(DisplayBackendUpdateError, match="packed elements|invalid image buffer"):
        backend.update(Image.new("RGB", (1200, 1600)))

    assert driver.calls == ["getbuffer"]


def test_missing_hardware_dependency_has_actionable_initialization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("hardware module unavailable")

    monkeypatch.setattr(waveshare_module, "import_module", fail_import)

    with pytest.raises(
        DisplayBackendInitializationError,
        match="Linux SPI/GPIO transport.*hardware module unavailable",
    ):
        create_display_backend("waveshare-13in3-e")


def test_poisoned_initialization_releases_resources_and_prevents_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = SimulatedDriver({"Init": [RuntimeError("Linux SPI/GPIO initialization failed")]})
    install_simulated_driver(monkeypatch, driver)
    module = ModuleType("epd13in3E")
    module.EPD = lambda: driver  # type: ignore[attr-defined]
    module.epdconfig = ModuleType("epdconfig")  # type: ignore[attr-defined]
    module.epdconfig.is_poisoned = lambda: True  # type: ignore[attr-defined]
    module.epdconfig.is_initialized = lambda: True  # type: ignore[attr-defined]
    module.epdconfig.module_exit = lambda: driver._call("module_exit")  # type: ignore[attr-defined]
    monkeypatch.setattr(waveshare_module, "import_module", lambda *_args, **_kwargs: module)
    backend = waveshare_module.WaveshareDisplayBackend()

    with pytest.raises(DisplayBackendInitializationError, match="Linux SPI/GPIO initialization failed") as failure:
        backend.update(Image.new("RGB", (1200, 1600)))
    assert not failure.value.recoverable
    with pytest.raises(DisplayBackendUpdateError, match="unrecoverable hardware failure") as failure:
        backend.update(Image.new("RGB", (1200, 1600)))
    assert not failure.value.recoverable

    assert driver.calls == ["getbuffer", "Init", "module_exit"]


def test_poisoned_communication_releases_resources_without_controller_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poisoned = [False]
    cleanup_attempts = [0]

    def release_resources() -> None:
        cleanup_attempts[0] += 1
        if cleanup_attempts[0] == 1:
            raise OSError("release failed")

    driver = SimulatedDriver(
        {"display": [RuntimeError("SPI transfer failed")]},
        hooks={"display": lambda: poisoned.__setitem__(0, True)},
    )
    module = ModuleType("refrain.display.vendor.waveshare.epd13in3E")
    module.EPD = lambda: driver  # type: ignore[attr-defined]
    module.epdconfig = ModuleType("epdconfig")  # type: ignore[attr-defined]
    module.epdconfig.is_poisoned = lambda: poisoned[0]  # type: ignore[attr-defined]
    module.epdconfig.is_initialized = lambda: True  # type: ignore[attr-defined]

    def module_exit() -> None:
        driver._call("module_exit")
        release_resources()

    module.epdconfig.module_exit = module_exit  # type: ignore[attr-defined]
    monkeypatch.setattr(waveshare_module, "import_module", lambda *_args, **_kwargs: module)
    backend = waveshare_module.WaveshareDisplayBackend()

    with pytest.raises(DisplayBackendUpdateError, match="SPI transfer failed") as failure:
        backend.update(Image.new("RGB", (1200, 1600)))
    assert not failure.value.recoverable
    with pytest.raises(DisplayBackendUpdateError, match="unrecoverable hardware failure"):
        backend.update(Image.new("RGB", (1200, 1600)))
    backend.close()

    assert driver.calls == ["getbuffer", "Init", "display", "module_exit", "module_exit"]
    assert cleanup_attempts == [2]


@pytest.mark.parametrize(
    ("operation", "error_type", "expected_calls"),
    [
        ("Init", DisplayBackendInitializationError, ["getbuffer", "Init"]),
        ("getbuffer", DisplayBackendUpdateError, ["getbuffer"]),
        ("display", DisplayBackendUpdateError, ["getbuffer", "Init", "display", "sleep"]),
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
        ("Init", DisplayBackendInitializationError, ["getbuffer", "Init"]),
        ("getbuffer", DisplayBackendUpdateError, ["getbuffer"]),
        ("display", DisplayBackendUpdateError, ["getbuffer", "Init", "display", "sleep"]),
        ("sleep", DisplayBackendUpdateError, ["getbuffer", "Init", "display", "sleep"]),
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


def test_cleanup_failure_does_not_mask_update_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = SimulatedDriver(
        {
            "display": [RuntimeError("presentation failed")],
            "sleep": [RuntimeError("cleanup failed")],
        }
    )
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(DisplayBackendUpdateError, match="presentation failed"):
        backend.update(Image.new("RGB", (1200, 1600)))
    backend.close()
    backend.close()
    assert driver.calls == ["getbuffer", "Init", "display", "sleep"]
    with pytest.raises(DisplayBackendUpdateError, match="closed Waveshare display"):
        backend.update(Image.new("RGB", (1200, 1600)))


def test_cleanup_failure_prevents_reinitialization(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = SimulatedDriver({"sleep": [RuntimeError("sleep failed")]})
    install_simulated_driver(monkeypatch, driver)
    backend = create_display_backend("waveshare-13in3-e")

    with pytest.raises(DisplayBackendUpdateError, match="sleep failed") as failure:
        backend.update(Image.new("RGB", (1200, 1600)))
    assert not failure.value.recoverable
    with pytest.raises(DisplayBackendUpdateError, match="unrecoverable hardware failure"):
        backend.update(Image.new("RGB", (1200, 1600)))

    assert driver.calls == ["getbuffer", "Init", "display", "sleep"]


def test_instances_serialize_process_global_hardware_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def block_first_init() -> None:
        first_entered.set()
        assert release_first.wait(timeout=2)

    first_driver = SimulatedDriver(hooks={"Init": block_first_init})
    second_driver = SimulatedDriver(hooks={"Init": second_entered.set})
    backends = []
    for driver in (first_driver, second_driver):
        module = ModuleType("epd13in3E")
        module.EPD = lambda driver=driver: driver  # type: ignore[attr-defined]
        monkeypatch.setattr(waveshare_module, "import_module", lambda *_args, module=module, **_kwargs: module)
        backends.append(waveshare_module.WaveshareDisplayBackend())

    errors: list[BaseException] = []

    def update(backend: Any) -> None:
        try:
            backend.update(Image.new("RGB", (1200, 1600)))
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=update, args=(backends[0],))
    second = threading.Thread(target=update, args=(backends[1],))
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert second_entered.is_set()

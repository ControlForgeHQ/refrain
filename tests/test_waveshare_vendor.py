from __future__ import annotations

import ctypes
import importlib.util
import io
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_VENDOR = Path(__file__).parent.parent / "src/refrain/display/vendor/waveshare"


class NativeFunction:
    def __init__(self, name: str, events: list[str], result: Any = None) -> None:
        self.name = name
        self.events = events
        self.result = result
        self.restype: Any = None

    def __call__(self, *_args: Any) -> Any:
        self.events.append(self.name)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NativeLibrary:
    def __init__(self, events: list[str], init_result: int = 0, close_result: int = 1) -> None:
        self.DEV_ModuleInit = NativeFunction("module-init", events, init_result)
        self.DEV_ModuleExit = NativeFunction("module-exit", events)
        self.DEV_Digital_Write = NativeFunction("digital-write", events)
        self.bcm2835_close = NativeFunction("bcm2835-close", events, close_result)
        self.loaded_path: str | None = None


def load_epdconfig(
    monkeypatch: pytest.MonkeyPatch,
    *,
    variant: str,
    init_result: int = 0,
    close_result: int = 1,
    library_present: bool = True,
    library_directory: str | os.PathLike[str] | None = None,
) -> tuple[ModuleType, NativeLibrary, list[str]]:
    events: list[str] = []
    library = NativeLibrary(events, init_result, close_result)
    selected_path = f"DEV_Config_64_{variant}.so"
    monkeypatch.setattr(
        ctypes,
        "CDLL",
        lambda path: (setattr(library, "loaded_path", path), library)[1],
    )
    original_exists = os.path.exists
    candidate_paths = {
        os.path.normcase(os.path.abspath(os.path.join(directory, selected_path)))
        for directory in (_VENDOR.resolve(), Path("/usr/local/lib"), Path("/usr/lib"))
    }
    selected_library_path = (
        None
        if library_directory is None
        else os.path.normcase(os.path.abspath(os.path.join(library_directory, selected_path)))
    )

    def exists(path: str | os.PathLike[str]) -> bool:
        normalized_path = os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))
        if normalized_path in candidate_paths:
            return library_present and (selected_library_path is None or normalized_path == selected_library_path)
        return original_exists(path)

    monkeypatch.setattr(os.path, "exists", exists)
    monkeypatch.setattr(
        "os.popen",
        lambda command: io.StringIO(
            "64\n" if command == "getconf LONG_BIT" else ("Raspberry Pi 5" if variant == "w" else "")
        ),
    )
    spec = importlib.util.spec_from_file_location(
        f"refrain.display.vendor.waveshare.epdconfig_test_{variant}_{init_result}_{close_result}",
        _VENDOR / "epdconfig.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, library, events


def test_missing_external_library_error_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    message = r"DEV_Config_64_b\.so.*Waveshare.*beside epdconfig\.py.*usr/local/lib.*usr/lib"
    with pytest.raises(RuntimeError, match=message):
        load_epdconfig(monkeypatch, variant="b", library_present=False)


def test_external_library_is_loaded_from_existing_search_path(monkeypatch: pytest.MonkeyPatch) -> None:
    module, library, _events = load_epdconfig(
        monkeypatch,
        variant="b",
        library_directory=Path("/usr/local/lib"),
    )

    assert library.loaded_path is not None
    expected_path = os.path.join("/usr/local/lib", "DEV_Config_64_b.so")
    assert os.path.normcase(os.path.abspath(library.loaded_path)) == os.path.normcase(os.path.abspath(expected_path))
    assert os.path.exists(Path("/usr/local/lib") / "DEV_Config_64_b.so")
    assert os.path.exists(_VENDOR / "epdconfig.py")
    assert module.spi is library


@pytest.mark.parametrize("variant", ["b", "w"])
def test_native_initialization_failure_stops_before_gpio_or_cleanup(
    monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    module, _library, events = load_epdconfig(monkeypatch, variant=variant, init_result=1)

    with pytest.raises(RuntimeError, match="DEV_ModuleInit failed with status 1"):
        module.module_init()

    assert events == ["module-init"]
    assert not module.is_initialized()
    assert module.is_poisoned()
    with pytest.raises(RuntimeError, match="poisoned"):
        module.module_init()
    assert events == ["module-init"]


def test_bcm2835_cleanup_calls_gpio_exit_before_mapping_close_and_can_reinitialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, library, events = load_epdconfig(monkeypatch, variant="b")
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module.module_init()
    module.module_exit()
    module.module_init()
    module.module_exit()

    assert library.DEV_ModuleInit.restype is ctypes.c_ubyte
    assert library.bcm2835_close.restype is ctypes.c_ubyte
    assert events.count("module-init") == 2
    assert events.count("module-exit") == 2
    assert events.count("bcm2835-close") == 2
    assert events.index("module-exit") < events.index("bcm2835-close")
    assert events[-2:] == ["module-exit", "bcm2835-close"]


def test_failed_bcm2835_close_poison_state_and_prevents_reinitialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _library, events = load_epdconfig(monkeypatch, variant="b", close_result=0)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    module.module_init()

    with pytest.raises(RuntimeError, match="bcm2835_close failed"):
        module.module_exit()
    before_retry = list(events)
    with pytest.raises(RuntimeError, match="poisoned"):
        module.module_init()

    assert module.is_poisoned()
    assert events == before_retry


def test_wiringpi_exit_does_not_apply_bcm2835_close_return_convention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, library, events = load_epdconfig(monkeypatch, variant="w")
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    library.DEV_ModuleExit.result = 1

    module.module_init()
    module.module_exit()

    assert library.DEV_ModuleInit.restype is ctypes.c_ubyte
    assert library.DEV_ModuleExit.restype is None
    assert "bcm2835-close" not in events
    assert events[-1] == "module-exit"
    assert not module.is_initialized()


def test_busy_polling_uses_a_bounded_monotonic_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    import refrain.display.vendor.waveshare as vendor_package

    clock = [0.0]
    delays: list[int] = []
    epdconfig = ModuleType("epdconfig")
    epdconfig.EPD_BUSY_PIN = 24  # type: ignore[attr-defined]
    epdconfig.digital_read = lambda _pin: 0  # type: ignore[attr-defined]

    def delay(milliseconds: int) -> None:
        delays.append(milliseconds)
        clock[0] += milliseconds / 1000

    epdconfig.delay_ms = delay  # type: ignore[attr-defined]
    monkeypatch.setattr(vendor_package, "epdconfig", epdconfig, raising=False)
    spec = importlib.util.spec_from_file_location(
        "refrain.display.vendor.waveshare.epd13in3E_timeout_test",
        _VENDOR / "epd13in3E.py",
    )
    assert spec is not None and spec.loader is not None
    driver_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver_module)
    driver_module.BUSY_TIMEOUT_SECONDS = 0.01
    monkeypatch.setattr(driver_module.time, "monotonic", lambda: clock[0])
    epd = driver_module.EPD.__new__(driver_module.EPD)
    epd.EPD_BUSY_PIN = 24

    with pytest.raises(TimeoutError, match="BUSY signal did not clear"):
        epd.ReadBusyH()

    assert delays == [5, 5]

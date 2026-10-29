from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

from refrain.display import (
    DisplayBackend,
    DisplayBackendCloseError,
    DisplayBackendError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
    create_display_backend,
)
from refrain.display.window import WindowDisplayBackend


class FakeRoot:
    def __init__(self) -> None:
        self._callbacks: list[Any] = []
        self._ready = threading.Condition()
        self._stopped = False
        self.mainloop_running = False
        self.destroyed = False
        self.title_text = ""
        self.close_protocol: Any = None

    def title(self, value: str) -> None:
        self.title_text = value

    def protocol(self, _name: str, callback: Any) -> None:
        self.close_protocol = callback

    def after(self, _milliseconds: int, callback: Any) -> None:
        with self._ready:
            self._callbacks.append(callback)
            self._ready.notify()

    def mainloop(self) -> None:
        self.mainloop_running = True
        while True:
            with self._ready:
                while not self._callbacks and not self._stopped:
                    self._ready.wait(timeout=0.1)
                if self._stopped:
                    self.mainloop_running = False
                    return
                callback = self._callbacks.pop(0)
            callback()

    def destroy(self) -> None:
        self.destroyed = True
        with self._ready:
            self._stopped = True
            self._ready.notify_all()

    def quit(self) -> None:
        with self._ready:
            self._stopped = True
            self._ready.notify_all()


class FakeLabel:
    def __init__(self, _root: FakeRoot) -> None:
        self.images: list[Any] = []

    def pack(self) -> None:
        pass

    def configure(self, *, image: Any) -> None:
        self.images.append(image)


def install_fake_gui(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initialization_error: Exception | None = None,
    photo_error: Exception | None = None,
    close_error: Exception | None = None,
) -> tuple[list[FakeRoot], list[Image.Image]]:
    roots: list[FakeRoot] = []
    presented_images: list[Image.Image] = []

    def create_root() -> FakeRoot:
        if initialization_error is not None:
            raise initialization_error
        root = FakeRoot()
        if close_error is not None:

            def fail_close() -> None:
                raise close_error

            root.destroy = fail_close  # type: ignore[method-assign]
        roots.append(root)
        return root

    class FakePhotoImage:
        def __init__(self, *, image: Image.Image) -> None:
            if photo_error is not None:
                raise photo_error
            presented_images.append(image)

    tkinter = ModuleType("tkinter")
    tkinter.Tk = create_root  # type: ignore[attr-defined]
    tkinter.Label = FakeLabel  # type: ignore[attr-defined]
    image_tk = ModuleType("PIL.ImageTk")
    image_tk.PhotoImage = FakePhotoImage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setitem(sys.modules, "PIL.ImageTk", image_tk)
    return roots, presented_images


def test_factory_constructs_the_explicit_window_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_gui(monkeypatch)

    backend = create_display_backend("window")

    assert isinstance(backend, DisplayBackend)
    assert isinstance(backend, WindowDisplayBackend)
    backend.close()


def test_factory_reports_unknown_backends() -> None:
    with pytest.raises(DisplayBackendError, match="unsupported display backend"):
        create_display_backend("unexpected")


def test_window_updates_replace_image_and_preserve_caller_image(monkeypatch: pytest.MonkeyPatch) -> None:
    roots, presented_images = install_fake_gui(monkeypatch)
    backend = WindowDisplayBackend()
    first = Image.new("RGB", (4, 3), "red")
    second = Image.new("RGBA", (2, 5), (10, 20, 30, 40))
    before = [(image.mode, image.size, image.tobytes()) for image in (first, second)]

    backend.update(first)
    backend.update(second)

    assert len(roots) == 1
    assert roots[0].mainloop_running
    assert roots[0].title_text == "Refrain"
    assert len(backend._label.images) == 2
    assert presented_images == [first, second]
    assert [(image.mode, image.size, image.tobytes()) for image in (first, second)] == before

    backend.close()

    assert roots[0].destroyed
    assert not roots[0].mainloop_running


def test_invalid_image_and_presentation_failures_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_gui(monkeypatch, photo_error=RuntimeError("conversion failed"))
    backend = WindowDisplayBackend()

    with pytest.raises(DisplayBackendUpdateError, match="Pillow Image.Image"):
        backend.update(object())  # type: ignore[arg-type]
    with pytest.raises(DisplayBackendUpdateError, match="could not present.*conversion failed"):
        backend.update(Image.new("RGB", (2, 2), "white"))

    backend.close()


def test_updates_after_close_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_gui(monkeypatch)
    backend = WindowDisplayBackend()
    backend.close()

    with pytest.raises(DisplayBackendUpdateError, match="closed desktop display") as failure:
        backend.update(Image.new("RGB", (1, 1)))
    assert not failure.value.recoverable


def test_window_manager_close_is_clean_and_updates_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    roots, _presented_images = install_fake_gui(monkeypatch)
    backend = WindowDisplayBackend()

    roots[0].close_protocol()
    backend.close()

    assert roots[0].destroyed
    with pytest.raises(DisplayBackendUpdateError, match="closed desktop display") as failure:
        backend.update(Image.new("RGB", (1, 1)))
    assert not failure.value.recoverable


def test_gui_initialization_failure_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_gui(monkeypatch, initialization_error=RuntimeError("no display"))

    with pytest.raises(DisplayBackendInitializationError, match="graphical session.*no display"):
        WindowDisplayBackend()


def test_close_failure_is_reported_without_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_gui(monkeypatch, close_error=RuntimeError("destroy failed"))
    backend = WindowDisplayBackend()

    with pytest.raises(DisplayBackendCloseError, match="destroy failed"):
        backend.close()


def test_core_imports_do_not_load_desktop_gui_modules() -> None:
    project_root = Path(__file__).parent.parent
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(project_root / "src"), environment.get("PYTHONPATH", "")))
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import refrain; import refrain.config; import refrain.renderer; "
                "import refrain.display; "
                "assert 'tkinter' not in sys.modules; assert 'PIL.ImageTk' not in sys.modules; "
                "assert not any(name.startswith('refrain.display.vendor.waveshare') for name in sys.modules)"
            ),
        ],
        cwd=project_root,
        env=environment,
        check=True,
    )

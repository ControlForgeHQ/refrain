"""Tk-based desktop window display backend."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any

from PIL import Image

from . import (
    DisplayBackendCloseError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
)


@dataclass
class _Command:
    action: Callable[[], None]
    shutdown: bool = False
    completed: Event = field(default_factory=Event)
    error: BaseException | None = None


class WindowDisplayBackend:
    """Show complete Pillow images in one responsive desktop window."""

    def __init__(self) -> None:
        self._commands: Queue[_Command] = Queue()
        self._lock = Lock()
        self._ready = Event()
        self._closed = False
        self._startup_error: BaseException | None = None
        self._worker_error: BaseException | None = None
        self._root: Any = None
        self._label: Any = None
        self._image_tk: Any = None
        self._photo_image: Any = None
        self._thread = Thread(target=self._run, name="refrain-window-display", daemon=True)
        try:
            self._thread.start()
        except RuntimeError as error:
            raise DisplayBackendInitializationError(f"could not start the desktop display thread: {error}") from error
        self._ready.wait()
        if self._startup_error is not None:
            self._thread.join()
            raise DisplayBackendInitializationError(
                f"could not initialize the desktop window; install Tk support and use a graphical session: "
                f"{self._startup_error}"
            ) from self._startup_error

    def _run(self) -> None:
        try:
            import tkinter as tk

            from PIL import ImageTk

            root = tk.Tk()
            root.title("Refrain")
            label = tk.Label(root)
            label.pack()
            root.protocol("WM_DELETE_WINDOW", self._close_from_window_manager)
            self._root = root
            self._label = label
            self._image_tk = ImageTk
            root.after(10, self._process_commands)
        except BaseException as error:
            self._startup_error = error
            self._ready.set()
            return

        self._ready.set()
        try:
            self._root.mainloop()
        except BaseException as error:
            self._worker_error = error
        finally:
            with self._lock:
                self._closed = True
            self._fail_pending(self._worker_error or RuntimeError("the desktop window was closed"))

    def _close_from_window_manager(self) -> None:
        with self._lock:
            if not self._closed:
                self._root.destroy()
                self._closed = True

    def _process_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                break
            try:
                command.action()
            except BaseException as error:
                command.error = error
            finally:
                command.completed.set()
            if command.shutdown:
                if command.error is not None:
                    try:
                        self._root.quit()
                    except BaseException:
                        pass
                return
        self._root.after(10, self._process_commands)

    def _fail_pending(self, error: BaseException) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                return
            command.error = error
            command.completed.set()

    def update(self, image: Image.Image) -> None:
        """Synchronously replace the window contents with a caller-owned image."""
        if not isinstance(image, Image.Image):
            raise DisplayBackendUpdateError("image must be a Pillow Image.Image instance")
        if image.width <= 0 or image.height <= 0:
            raise DisplayBackendUpdateError("image must have positive width and height")

        def present() -> None:
            photo_image = self._image_tk.PhotoImage(image=image)
            self._label.configure(image=photo_image)
            self._photo_image = photo_image

        with self._lock:
            if self._closed:
                raise DisplayBackendUpdateError("cannot update a closed desktop display", recoverable=False)
            if not self._thread.is_alive():
                raise DisplayBackendUpdateError(
                    f"the desktop display window is no longer available: {self._worker_error or 'closed'}",
                    recoverable=False,
                )
            command = _Command(present)
            self._commands.put(command)
        command.completed.wait()
        if command.error is not None:
            message = f"could not present the image in the desktop window: {command.error}"
            raise DisplayBackendUpdateError(message, recoverable=not self._closed) from command.error

    def close(self) -> None:
        """Close the window and wait for its GUI thread to release resources."""
        with self._lock:
            if self._closed:
                command = None
            elif self._thread.is_alive():
                self._closed = True
                command = _Command(self._root.destroy, shutdown=True)
                self._commands.put(command)
            else:
                self._closed = True
                command = None

        if command is not None:
            command.completed.wait()
        self._thread.join()
        error = command.error if command is not None else self._worker_error
        if error is not None:
            raise DisplayBackendCloseError(f"could not close the desktop display window: {error}") from error

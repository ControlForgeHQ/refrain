"""Tk-based desktop window display backend."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any

from PIL import Image

from ..config import DisplayOutputConfiguration
from . import (
    DisplayBackendCloseError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
)


@dataclass
class _Command:
    action: Callable[[], None] | None
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
        self._user_closed = False
        self._withdrawal_callback: Callable[[], None] | None = None
        self._startup_error: BaseException | None = None
        self._worker_error: BaseException | None = None
        self._root: Any = None
        self._label: Any = None
        self._image_tk: Any = None
        self._photo_image: Any = None
        self._root_destroyed = False
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
            try:
                import tkinter as tk

                from PIL import ImageTk

                self._root = tk.Tk()
                self._root.title("Refrain")
                self._label = tk.Label(self._root)
                self._label.pack()
                self._root.protocol("WM_DELETE_WINDOW", self._close_from_window_manager)
                self._image_tk = ImageTk
                self._root.after(10, self._process_commands)
            except BaseException as error:
                # GUI tracebacks can retain interpreter owners across threads.
                self._startup_error = RuntimeError(str(error))
                return

            self._ready.set()
            try:
                self._root.mainloop()
            except BaseException as error:
                self._worker_error = RuntimeError(str(error))
        finally:
            with self._lock:
                self._closed = True
            try:
                if self._root is not None and not self._root_destroyed:
                    self._destroy_root()
            except BaseException as error:
                self._worker_error = self._worker_error or RuntimeError(str(error))
            finally:
                self._photo_image = None
                self._label = None
                self._root = None
                self._image_tk = None
            self._fail_pending(self._worker_error or RuntimeError("the desktop window was closed"))
            self._ready.set()

    def _destroy_root(self) -> None:
        self._root.destroy()
        self._root_destroyed = True

    def _close_from_window_manager(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._destroy_root()
            self._closed = True
            self._user_closed = True
            # Keep updates from observing closure before the coordinator sees withdrawal.
            if self._withdrawal_callback is not None:
                self._withdrawal_callback()

    def set_withdrawal_callback(self, callback: Callable[[], None]) -> None:
        """Notify the owner of a user close, including one before registration."""
        with self._lock:
            if self._withdrawal_callback is not None:
                raise RuntimeError("desktop display withdrawal callback is already registered")
            self._withdrawal_callback = callback
            user_closed = self._user_closed
        if user_closed:
            callback()

    def _process_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                break
            try:
                if command.action is not None:
                    command.action()
            except BaseException as error:
                command.error = RuntimeError(str(error))
            finally:
                command.action = None
                command.completed.set()
            if command.shutdown or self._root_destroyed:
                if command.error is not None:
                    self._worker_error = command.error
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
            command.action = None
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
            self._root.geometry(f"{image.width}x{image.height}")

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

    def publish(self, destination: DisplayOutputConfiguration, image: Image.Image) -> None:
        """Present the image through this configured single-output destination."""
        del destination
        self.update(image)

    def close(self) -> None:
        """Close the window and wait for its GUI thread to release resources."""
        with self._lock:
            if self._closed:
                command = None
            elif self._thread.is_alive():
                self._closed = True
                command = _Command(self._destroy_root, shutdown=True)
                self._commands.put(command)
            else:
                self._closed = True
                command = None

        if command is not None:
            command.completed.wait()
        self._thread.join()
        error = (command.error if command is not None else None) or self._worker_error
        if error is not None:
            raise DisplayBackendCloseError(f"could not close the desktop display window: {error}") from error

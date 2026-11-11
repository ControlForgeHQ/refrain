"""Exclusive per-user ownership of the Refrain installation."""

from __future__ import annotations

import errno
import logging
import os
import stat
from collections.abc import Callable
from pathlib import Path
from threading import Thread

if os.name == "nt":
    import ctypes
    import msvcrt
else:
    import fcntl
    import pwd

_LOGGER = logging.getLogger(__name__)


class OwnershipError(Exception):
    """Raised when installation ownership cannot be acquired or released."""


def _user_home() -> Path:
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x28, None, 0, buffer)
        if result != 0 or not buffer.value:
            raise OSError(f"cannot resolve the Windows user profile directory (HRESULT {result:#x})")
        return Path(buffer.value)
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


class InstallationOwnership:
    """A non-blocking operating-system lock, independent of runtime storage paths."""

    def __init__(self, path: Path | None = None) -> None:
        try:
            self.path = path if path is not None else _user_home() / ".refrain-ownership.lock"
        except (OSError, RuntimeError, KeyError) as error:
            raise OwnershipError(f"cannot determine the per-user ownership lock location: {error}") from error
        self._fd: int | None = None
        self._pending_workers: tuple[Thread, ...] = ()
        self._finish_shutdown: Callable[[], object] | None = None

    def ensure_outside(self, roots: tuple[Path, ...]) -> None:
        """Refuse operations that could remove the lock while it is held."""
        try:
            lock_path = self.path.resolve()
            if any(lock_path.is_relative_to(Path(root).resolve()) for root in roots):
                raise OwnershipError(
                    f"ownership lock {self.path} is inside a standard installation tree; "
                    "correct the per-user installation paths before retrying"
                )
        except (OSError, RuntimeError) as error:
            raise OwnershipError(f"cannot verify ownership lock location {self.path}: {error}") from error

    def acquire(self) -> None:
        if self._fd is not None:
            raise OwnershipError("Refrain installation ownership is already held by this object")
        try:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOINHERIT", 0)
            fd = os.open(self.path, flags, 0o600)
        except (OSError, ValueError) as error:
            raise OwnershipError(f"cannot open Refrain ownership lock {self.path}: {error}") from error
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OwnershipError(f"Refrain ownership lock is not a regular file: {self.path}")
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise OwnershipError(
                        "another Refrain runtime, demo, or installation operation owns the installation; "
                        "stop it and retry"
                    ) from error
                raise
        except BaseException as error:
            try:
                os.close(fd)
            except OSError as close_error:
                raise OwnershipError(f"cannot close Refrain ownership lock {self.path}: {close_error}") from close_error
            if isinstance(error, OSError):
                raise OwnershipError(f"cannot acquire Refrain ownership lock {self.path}: {error}") from error
            raise
        self._fd = fd

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as error:
            raise OwnershipError(f"cannot release Refrain ownership lock {self.path}: {error}") from error
        finally:
            try:
                os.close(fd)
            except OSError as error:
                raise OwnershipError(f"cannot close Refrain ownership lock {self.path}: {error}") from error

    def defer_release_until(self, workers: tuple[Thread, ...], finish_shutdown: Callable[[], object]) -> None:
        """Retain ownership if bounded backend shutdown leaves workers active."""
        self._pending_workers = workers
        self._finish_shutdown = finish_shutdown

    def _release_after_workers(self) -> None:
        for worker in self._pending_workers:
            worker.join()
        try:
            if self._finish_shutdown is not None:
                self._finish_shutdown()
        except Exception:
            _LOGGER.exception("Display cleanup failed after workers stopped")
        try:
            self.release()
        except OwnershipError:
            _LOGGER.exception("Refrain ownership cleanup failed after display workers stopped")

    def __enter__(self) -> InstallationOwnership:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._pending_workers:
            try:
                Thread(target=self._release_after_workers, name="refrain-ownership-cleanup", daemon=True).start()
            except RuntimeError as error:
                raise OwnershipError(f"cannot schedule Refrain ownership cleanup: {error}") from error
        else:
            self.release()

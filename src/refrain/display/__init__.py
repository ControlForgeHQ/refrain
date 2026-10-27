"""Hardware-independent interfaces and construction for display backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image


@runtime_checkable
class DisplayBackend(Protocol):
    """Present complete caller-owned Pillow images."""

    def update(self, image: Image.Image) -> None:
        """Present one complete image without modifying or closing it."""
        ...

    def close(self) -> None:
        """Release resources owned by this backend."""
        ...


class DisplayBackendError(RuntimeError):
    """Base class for display-backend construction and operation failures."""


class DisplayBackendUnavailableError(DisplayBackendError):
    """Raised when a recognized display backend has not been implemented."""


class DisplayBackendInitializationError(DisplayBackendError):
    """Raised when a display backend cannot initialize its presentation resources."""


class DisplayBackendUpdateError(DisplayBackendError):
    """Raised when an image cannot be presented."""


class DisplayBackendCloseError(DisplayBackendError):
    """Raised when backend resources cannot be released."""


def create_display_backend(backend: str) -> DisplayBackend:
    """Construct an explicitly selected built-in display backend."""
    if backend == "window":
        from .window import WindowDisplayBackend

        return WindowDisplayBackend()
    if backend == "waveshare-13in3-e":
        raise DisplayBackendUnavailableError(
            "display backend 'waveshare-13in3-e' is recognized but not implemented yet"
        )
    raise DisplayBackendError(f"unsupported display backend {backend!r}; choose 'window' or 'waveshare-13in3-e'")


__all__ = [
    "DisplayBackend",
    "DisplayBackendCloseError",
    "DisplayBackendError",
    "DisplayBackendInitializationError",
    "DisplayBackendUnavailableError",
    "DisplayBackendUpdateError",
    "create_display_backend",
]

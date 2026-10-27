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


def create_display_backend(
    backend: str,
    *,
    image_server_host: str = "127.0.0.1",
    image_server_port: int = 8080,
) -> DisplayBackend:
    """Construct an explicitly selected built-in display backend."""
    if backend == "window":
        from .window import WindowDisplayBackend

        return WindowDisplayBackend()
    if backend == "waveshare-13in3-e":
        from .waveshare import WaveshareDisplayBackend

        return WaveshareDisplayBackend()
    if backend == "image-server":
        from .image_server import ImageServerDisplayBackend

        return ImageServerDisplayBackend(host=image_server_host, port=image_server_port)
    raise DisplayBackendError(
        f"unsupported display backend {backend!r}; choose 'window', 'waveshare-13in3-e', or 'image-server'"
    )


__all__ = [
    "DisplayBackend",
    "DisplayBackendCloseError",
    "DisplayBackendError",
    "DisplayBackendInitializationError",
    "DisplayBackendUnavailableError",
    "DisplayBackendUpdateError",
    "create_display_backend",
]

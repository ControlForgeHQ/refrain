"""Hardware-independent interfaces and construction for display backends."""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from PIL import Image

from ..config import DisplayOutputConfiguration


@runtime_checkable
class DisplayBackend(Protocol):
    """Present complete caller-owned images through configured destinations."""

    def publish(self, destination: DisplayOutputConfiguration, image: Image.Image) -> None:
        """Present one complete image through the selected configured destination."""
        ...

    def close(self) -> None:
        """Release resources owned by this backend."""
        ...


@runtime_checkable
class PublicationDisplayBackend(Protocol):
    """Optionally store completed publication metadata alongside destination images."""

    def publish_scheduled(
        self,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        completed_metadata: dict[str, object],
    ) -> None:
        """Publish one scheduled image with its completed application-finalized metadata."""
        ...

    def publish_transient(
        self,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        completed_metadata: dict[str, object],
    ) -> None:
        """Publish one complete transient image with its completed application-finalized metadata."""
        ...


@runtime_checkable
class WithdrawableDisplayBackend(Protocol):
    """Optionally report intentional user withdrawal of a backend's destinations."""

    def set_withdrawal_callback(self, callback: Callable[[], None]) -> None:
        """Register the owner notification, including any earlier user withdrawal."""
        ...


class DisplayBackendError(RuntimeError):
    """Base class for display-backend construction and operation failures."""

    def __init__(self, message: str, *, recoverable: bool = True) -> None:
        self.recoverable = recoverable
        super().__init__(message)


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
    publication_store: object | None = None,
) -> DisplayBackend:
    """Construct an explicitly selected built-in display backend."""
    if backend == "window":
        from .window import WindowDisplayBackend

        return WindowDisplayBackend()
    if backend == "waveshare-13in3-e":
        from .waveshare import WaveshareDisplayBackend

        return WaveshareDisplayBackend()
    if backend == "publish":
        from .publication import FilesystemPublicationDisplayBackend

        if publication_store is None:
            raise DisplayBackendInitializationError("publish backend requires a configured publication store")
        return FilesystemPublicationDisplayBackend(publication_store)
    raise DisplayBackendError(
        f"unsupported display backend {backend!r}; choose " "'window', 'waveshare-13in3-e', or 'publish'"
    )


__all__ = [
    "DisplayBackend",
    "DisplayBackendCloseError",
    "DisplayBackendError",
    "DisplayBackendInitializationError",
    "DisplayBackendUnavailableError",
    "DisplayBackendUpdateError",
    "PublicationDisplayBackend",
    "create_display_backend",
]

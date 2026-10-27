"""Waveshare 13.3-inch e-Paper HAT+ (E) display backend."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from threading import Lock
from typing import Any

from PIL import Image

from . import (
    DisplayBackendCloseError,
    DisplayBackendError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
)


class WaveshareDisplayBackend:
    """Present complete Pillow images on the Waveshare 13.3-inch E panel."""

    _SUPPORTED_SIZES = {(1200, 1600), (1600, 1200)}

    def __init__(self) -> None:
        self._lock = Lock()
        self._closed = False
        self._awake = False
        try:
            driver = import_module(".vendor.waveshare.epd13in3E", package="refrain.display")
            self._epd = driver.EPD()
        except Exception as error:
            raise DisplayBackendInitializationError(
                "could not load the Waveshare 13.3-inch E driver; use a supported Raspberry Pi "
                f"installation with its bundled native library available: {error}"
            ) from error

    @staticmethod
    def _invoke(
        operation: Callable[[], Any],
        action: str,
        error_type: type[DisplayBackendError],
    ) -> Any:
        try:
            result = operation()
        except Exception as error:
            raise error_type(f"could not {action}: {error}") from error
        if result is False:
            raise error_type(f"the Waveshare driver reported failure while trying to {action}")
        return result

    def update(self, image: Image.Image) -> None:
        """Synchronously present a complete image without changing the caller's image."""
        if not isinstance(image, Image.Image):
            raise DisplayBackendUpdateError("image must be a Pillow Image.Image instance")
        if image.size not in self._SUPPORTED_SIZES:
            raise DisplayBackendUpdateError(
                f"image dimensions must be 1200 x 1600 or 1600 x 1200; got {image.width} x {image.height}"
            )

        with self._lock:
            if self._closed:
                raise DisplayBackendUpdateError("cannot update a closed Waveshare display")
            try:
                driver_image = image.copy()
            except Exception as error:
                raise DisplayBackendUpdateError(f"could not copy the image for display: {error}") from error

            try:
                self._awake = True
                try:
                    self._invoke(
                        lambda: self._epd.Init(),
                        "initialize the Waveshare display; check Raspberry Pi support and SPI/GPIO access",
                        DisplayBackendInitializationError,
                    )
                    buffer = self._invoke(
                        lambda: self._epd.getbuffer(driver_image),
                        "convert the image for the Waveshare display",
                        DisplayBackendUpdateError,
                    )
                    if not buffer:
                        raise DisplayBackendUpdateError("the Waveshare driver returned an empty image buffer")
                    self._invoke(
                        lambda: self._epd.display(buffer),
                        "present the image on the Waveshare display",
                        DisplayBackendUpdateError,
                    )
                except Exception:
                    if self._awake:
                        try:
                            self._invoke(
                                lambda: self._epd.sleep(),
                                "return the Waveshare controller to sleep",
                                DisplayBackendUpdateError,
                            )
                        except Exception:
                            pass
                        else:
                            self._awake = False
                    raise
                else:
                    self._invoke(
                        lambda: self._epd.sleep(),
                        "return the Waveshare controller to sleep",
                        DisplayBackendUpdateError,
                    )
                    self._awake = False
            finally:
                try:
                    driver_image.close()
                except Exception:
                    pass

    def close(self) -> None:
        """Return an active controller to sleep; repeated calls are safe."""
        with self._lock:
            if self._closed and not self._awake:
                return
            self._closed = True
            if not self._awake:
                return
            self._invoke(
                lambda: self._epd.sleep(),
                "return the Waveshare controller to sleep during close",
                DisplayBackendCloseError,
            )
            self._awake = False

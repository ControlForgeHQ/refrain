"""Waveshare 13.3-inch e-Paper HAT+ (E) display backend."""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module
from threading import Lock, RLock
from typing import Any

from PIL import Image

from . import (
    DisplayBackendCloseError,
    DisplayBackendError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
)

_HARDWARE_LOCK = RLock()
_LOGGER = logging.getLogger(__name__)


class WaveshareDisplayBackend:
    """Present complete Pillow images on the Waveshare 13.3-inch E panel."""

    _SUPPORTED_SIZES = {(1200, 1600), (1600, 1200)}
    _SUPPORTED_MODES = {"RGB"}
    _BUFFER_LENGTH = 960_000

    def __init__(self) -> None:
        self._lock = Lock()
        self._closed = False
        self._failed = False
        self._initialized = False
        try:
            driver = import_module(".vendor.waveshare.epd13in3E", package="refrain.display")
            self._driver_module = driver
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
        if image.mode not in self._SUPPORTED_MODES:
            raise DisplayBackendUpdateError(
                f"image mode must be RGB; got {image.mode!r}. Alpha and palette transparency are unsupported"
            )

        with self._lock:
            if self._closed:
                raise DisplayBackendUpdateError("cannot update a closed Waveshare display")
            if self._failed:
                raise DisplayBackendUpdateError("cannot update a Waveshare display after a hardware cleanup failure")
            try:
                driver_image = image.copy()
            except Exception as error:
                raise DisplayBackendUpdateError(f"could not copy the image for display: {error}") from error

            try:
                buffer = self._invoke(
                    lambda: self._epd.getbuffer(driver_image),
                    "convert the image for the Waveshare display",
                    DisplayBackendUpdateError,
                )
                try:
                    buffer_length = len(buffer)
                except Exception as error:
                    raise DisplayBackendUpdateError(
                        f"the Waveshare driver returned an invalid image buffer: {error}"
                    ) from error
                if buffer_length != self._BUFFER_LENGTH:
                    raise DisplayBackendUpdateError(
                        f"the Waveshare driver returned {buffer_length} packed elements; "
                        f"expected {self._BUFFER_LENGTH}"
                    )

                with _HARDWARE_LOCK:
                    try:
                        self._invoke(
                            lambda: self._epd.Init(),
                            "initialize the Waveshare display; check Raspberry Pi support and GPIO access",
                            DisplayBackendInitializationError,
                        )
                    except Exception:
                        if self._native_is_poisoned():
                            self._failed = True
                        elif self._native_is_initialized():
                            try:
                                self._driver_module.epdconfig.module_exit()
                            except Exception:
                                self._failed = True
                                _LOGGER.exception(
                                    "failed to release native GPIO after Waveshare initialization failure"
                                )
                        raise
                    self._initialized = True
                    try:
                        self._invoke(
                            lambda: self._epd.display(buffer),
                            "present the image on the Waveshare display",
                            DisplayBackendUpdateError,
                        )
                        self._sleep_controller(DisplayBackendUpdateError)
                    except Exception:
                        if self._native_is_poisoned():
                            self._failed = True
                        if self._initialized and not self._failed:
                            try:
                                self._sleep_controller(DisplayBackendUpdateError)
                            except Exception:
                                _LOGGER.exception("failed to return Waveshare controller to sleep after update failure")
                        raise
            finally:
                try:
                    driver_image.close()
                except Exception:
                    pass

    def _native_is_poisoned(self) -> bool:
        config = getattr(self._driver_module, "epdconfig", None)
        checker = getattr(config, "is_poisoned", None)
        return checker() if checker is not None else False

    def _sleep_controller(self, error_type: type[DisplayBackendError]) -> None:
        try:
            self._invoke(
                lambda: self._epd.sleep(),
                "return the Waveshare controller to sleep",
                error_type,
            )
        except Exception:
            self._failed = True
            if self._native_is_initialized():
                try:
                    self._driver_module.epdconfig.module_exit()
                except Exception:
                    _LOGGER.exception("failed to release native GPIO mappings after controller sleep failure")
            raise
        else:
            self._initialized = False

    def _native_is_initialized(self) -> bool:
        config = getattr(self._driver_module, "epdconfig", None)
        checker = getattr(config, "is_initialized", None)
        return checker() if checker is not None else False

    def close(self) -> None:
        """Return an active controller to sleep; repeated calls are safe."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._failed or not self._initialized:
                return
            with _HARDWARE_LOCK:
                try:
                    self._sleep_controller(DisplayBackendCloseError)
                except DisplayBackendCloseError:
                    raise
                except Exception as error:
                    raise DisplayBackendCloseError(f"could not close the Waveshare display: {error}") from error

"""Independent publication workers for configured display backends."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Condition, Event, Thread
from typing import Callable

from PIL import Image

from ..config import DisplayBackendConfiguration
from . import DisplayBackend, DisplayBackendError, create_display_backend

_LOGGER = logging.getLogger(__name__)
_MAX_RETRY_DELAY = 60.0
_SHUTDOWN_TIMEOUT = 60.0


@dataclass
class _Presentation:
    identity: tuple[int, int]
    image: Image.Image
    references: int = 1


@dataclass
class _BackendState:
    configuration: DisplayBackendConfiguration
    backend: DisplayBackend | None = None
    successful_identity: tuple[int, int] | None = None
    terminal: bool = False
    error: str | None = None


class DisplayPublicationCoordinator:
    """Publish each latest prepared image on an independent synchronous backend worker."""

    def __init__(
        self,
        configurations: tuple[DisplayBackendConfiguration, ...],
        backend_factory: Callable[[DisplayBackendConfiguration], DisplayBackend] | None = None,
        *,
        retry: bool = True,
        all_unavailable_event: Event | None = None,
    ) -> None:
        self._condition = Condition()
        self._factory = backend_factory or self._default_factory
        self._retry = retry
        self._all_unavailable_event = all_unavailable_event
        self._stopping = False
        self._desired: _Presentation | None = None
        self._states = {configuration.type: _BackendState(configuration) for configuration in configurations}
        self._threads = [
            Thread(
                target=self._run_backend,
                args=(state,),
                name=f"refrain-display-{state.configuration.type}",
                daemon=True,
            )
            for state in self._states.values()
        ]
        for thread in self._threads:
            thread.start()

    @staticmethod
    def _default_factory(configuration: DisplayBackendConfiguration) -> DisplayBackend:
        return create_display_backend(
            configuration.type,
            image_server_host=configuration.host,
            image_server_port=configuration.port,
        )

    @property
    def desired_identity(self) -> tuple[int, int] | None:
        with self._condition:
            return None if self._desired is None else self._desired.identity

    @property
    def all_unavailable(self) -> bool:
        with self._condition:
            return bool(self._states) and all(state.terminal for state in self._states.values())

    @property
    def acknowledgements(self) -> dict[str, tuple[int, int] | None]:
        with self._condition:
            return {name: state.successful_identity for name, state in self._states.items()}

    def publish(self, identity: tuple[int, int], image: Image.Image) -> None:
        """Replace the pending desired image; ownership of ``image`` transfers to the coordinator."""
        with self._condition:
            if self._stopping:
                image.close()
                raise RuntimeError("display publication coordinator is stopping")
            if self._desired is not None and self._desired.identity == identity:
                image.close()
                return
            previous = self._desired
            self._desired = _Presentation(identity, image)
            self._release(previous)
            self._condition.notify_all()

    def clear_desired(self) -> None:
        """Discard an obsolete pending image without interrupting updates already in progress."""
        with self._condition:
            previous = self._desired
            self._desired = None
            self._release(previous)
            self._condition.notify_all()

    def wait_for_publication(self, identity: tuple[int, int], timeout: float | None = None) -> bool:
        """Wait until every backend succeeds or becomes terminal; return whether any succeeded."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while any(state.successful_identity != identity and not state.terminal for state in self._states.values()):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._condition.wait(remaining)
            return any(state.successful_identity == identity for state in self._states.values())

    def close(self) -> None:
        """Stop requests and wait a bounded time without interrupting active backend calls."""
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        deadline = time.monotonic() + _SHUTDOWN_TIMEOUT
        for thread in self._threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)
        for state, thread in zip(self._states.values(), self._threads, strict=True):
            if thread.is_alive():
                _LOGGER.error(
                    "Display backend %s did not stop within %.0f seconds; "
                    "its active update will not be interrupted or closed concurrently",
                    state.configuration.type,
                    _SHUTDOWN_TIMEOUT,
                )
        with self._condition:
            self._release(self._desired)
            self._desired = None

    def _release(self, presentation: _Presentation | None) -> None:
        if presentation is None:
            return
        presentation.references -= 1
        if presentation.references == 0:
            try:
                presentation.image.close()
            except Exception:
                _LOGGER.exception("Failed to release a prepared presentation image")

    def _wait_before_retry(self, delay: float) -> bool:
        deadline = time.monotonic() + delay
        with self._condition:
            while not self._stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                self._condition.wait(remaining)
            return False

    def _run_backend(self, state: _BackendState) -> None:
        name = state.configuration.type
        backend: DisplayBackend | None = None
        retry_delay = 1.0
        try:
            while True:
                with self._condition:
                    if self._stopping:
                        return
                if backend is None:
                    try:
                        backend = self._factory(state.configuration)
                    except Exception as error:
                        recoverable = isinstance(error, DisplayBackendError) and error.recoverable
                        with self._condition:
                            state.error = str(error)
                            state.terminal = not recoverable or not self._retry
                            self._signal_all_unavailable()
                            self._condition.notify_all()
                        if isinstance(error, DisplayBackendError):
                            _LOGGER.warning("Display backend %s initialization failed: %s", name, error)
                        else:
                            _LOGGER.exception("Unexpected display backend %s initialization failure", name)
                        if state.terminal:
                            return
                        if not self._wait_before_retry(retry_delay):
                            return
                        retry_delay = min(_MAX_RETRY_DELAY, retry_delay * 2)
                        continue
                    with self._condition:
                        state.backend = backend
                        state.error = None
                        self._condition.notify_all()
                    retry_delay = 1.0

                with self._condition:
                    while not self._stopping and (
                        self._desired is None or self._desired.identity == state.successful_identity
                    ):
                        self._condition.wait()
                    if self._stopping:
                        return
                    assert self._desired is not None
                    presentation = self._desired
                    presentation.references += 1

                try:
                    backend.update(presentation.image)
                except Exception as error:
                    recoverable = isinstance(error, DisplayBackendError) and error.recoverable
                    with self._condition:
                        state.error = str(error)
                        state.terminal = not recoverable or not self._retry
                        self._signal_all_unavailable()
                        self._condition.notify_all()
                    if isinstance(error, DisplayBackendError):
                        _LOGGER.warning("Display backend %s update failed: %s", name, error)
                    else:
                        _LOGGER.exception("Unexpected display backend %s update failure", name)
                    if state.terminal:
                        return
                    if not self._wait_before_retry(retry_delay):
                        return
                    retry_delay = min(_MAX_RETRY_DELAY, retry_delay * 2)
                    continue
                else:
                    with self._condition:
                        state.successful_identity = presentation.identity
                        state.error = None
                        self._condition.notify_all()
                    _LOGGER.info("Display backend %s published presentation %s", name, presentation.identity)
                    retry_delay = 1.0
                finally:
                    with self._condition:
                        self._release(presentation)
        except Exception as error:
            with self._condition:
                state.error = str(error)
                state.terminal = True
                self._signal_all_unavailable()
                self._condition.notify_all()
            _LOGGER.exception("Display backend %s worker terminated unexpectedly", name)
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception as error:
                    with self._condition:
                        state.error = str(error)
                        self._condition.notify_all()
                    _LOGGER.warning("Display backend %s cleanup failed: %s", name, error)
            with self._condition:
                state.backend = None
                self._condition.notify_all()

    def _signal_all_unavailable(self) -> None:
        if self._all_unavailable_event is not None and all(state.terminal for state in self._states.values()):
            self._all_unavailable_event.set()


__all__ = ["DisplayPublicationCoordinator"]

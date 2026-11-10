"""Independent publication workers for configured display destinations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread
from typing import Callable, Mapping

from PIL import Image

from ..config import DisplayBackendConfiguration, DisplayOutputConfiguration
from ..geometry import ResolvedOutputSpecification
from . import DisplayBackend, DisplayBackendError, create_display_backend

_LOGGER = logging.getLogger(__name__)
_MAX_RETRY_DELAY = 60.0
_SHUTDOWN_TIMEOUT = 60.0


@dataclass
class _Presentation:
    identity: tuple[int, int]
    images: Mapping[ResolvedOutputSpecification, Image.Image]
    references: int = 1


@dataclass
class _DestinationState:
    backend_configuration: DisplayBackendConfiguration
    destination: DisplayOutputConfiguration
    key: str
    successful_identity: tuple[int, int] | None = None
    successful_at: float | None = None
    terminal: bool = False
    error: str | None = None


class DisplayPublicationCoordinator:
    """Publish each destination's matching variant on an independent worker."""

    def __init__(
        self,
        configurations: tuple[DisplayBackendConfiguration, ...],
        backend_factory: Callable[[DisplayBackendConfiguration], DisplayBackend] | None = None,
        *,
        retry: bool = True,
        all_unavailable_event: Event | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._condition = Condition()
        self._factory = backend_factory or self._default_factory
        self._retry = retry
        self._all_unavailable_event = all_unavailable_event
        self._monotonic_clock = monotonic_clock
        self._stopping = False
        self._desired: _Presentation | None = None
        self._backend_configurations = {configuration.type: configuration for configuration in configurations}
        self._backend_locks = {backend_type: Lock() for backend_type in self._backend_configurations}
        self._backends: dict[str, DisplayBackend] = {}
        self._states = {
            f"{configuration.type}:{destination.identifier}": _DestinationState(
                configuration,
                destination,
                f"{configuration.type}:{destination.identifier}",
            )
            for configuration in configurations
            for destination in configuration.outputs
        }
        self._threads = [
            Thread(
                target=self._run_destination,
                args=(state,),
                name=f"refrain-display-{state.key}",
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
            image_server_output_ids=tuple(output.identifier for output in configuration.outputs),
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
            return {key: state.successful_identity for key, state in self._states.items()}

    def publish(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification, Image.Image],
    ) -> None:
        """Replace the pending desired variant set; ownership transfers to the coordinator."""
        with self._condition:
            if self._stopping:
                self._close_images(images)
                raise RuntimeError("display publication coordinator is stopping")
            if self._desired is not None and self._desired.identity == identity:
                self._close_images(images)
                return
            required = {
                state.destination.output_specification
                for state in self._states.values()
                if not state.terminal
            }
            if required - images.keys():
                self._close_images(images)
                raise ValueError(f"publication is missing output variants: {required - images.keys()}")
            previous = self._desired
            self._desired = _Presentation(identity, images)
            self._release(previous)
            self._condition.notify_all()

    def clear_desired(self) -> None:
        """Discard an obsolete pending variant set without interrupting active updates."""
        with self._condition:
            previous = self._desired
            self._desired = None
            self._release(previous)
            self._condition.notify_all()

    def wait_for_publication(self, identity: tuple[int, int], timeout: float | None = None) -> bool:
        """Wait until every destination succeeds or becomes terminal; return whether any succeeded."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while any(state.successful_identity != identity and not state.terminal for state in self._states.values()):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._condition.wait(remaining)
            return any(state.successful_identity == identity for state in self._states.values())

    def has_successful_publication(self, identity: tuple[int, int]) -> bool:
        with self._condition:
            return any(state.successful_identity == identity for state in self._states.values())

    def publication_results(self, identity: tuple[int, int]) -> dict[str, tuple[bool, str | None]]:
        with self._condition:
            return {
                key: (
                    state.successful_identity == identity,
                    None if state.successful_identity == identity else state.error,
                )
                for key, state in self._states.items()
            }

    def first_successful_publication_time(self, identity: tuple[int, int]) -> float | None:
        with self._condition:
            times = [
                state.successful_at
                for state in self._states.values()
                if state.successful_identity == identity and state.successful_at is not None
            ]
            return min(times) if times else None

    def wait_for_any_publication(
        self,
        identity: tuple[int, int],
        timeout: float | None = None,
        *,
        cancellation_event: Event | None = None,
    ) -> bool:
        """Wait for the first successful acknowledgement or for every destination to become terminal."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not any(state.successful_identity == identity for state in self._states.values()):
                if all(state.terminal for state in self._states.values()):
                    break
                if cancellation_event is not None and cancellation_event.is_set():
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                if cancellation_event is not None:
                    remaining = 0.25 if remaining is None else min(remaining, 0.25)
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
                    "Display destination %s did not stop within %.0f seconds; "
                    "its active update will not be interrupted or closed concurrently",
                    state.key,
                    _SHUTDOWN_TIMEOUT,
                )
        with self._condition:
            self._release(self._desired)
            self._desired = None
        active_backend_types = {
            state.backend_configuration.type
            for state, thread in zip(self._states.values(), self._threads, strict=True)
            if thread.is_alive()
        }
        for backend_type, backend in self._backends.items():
            if backend_type in active_backend_types:
                _LOGGER.error(
                    "Display backend %s remains in use by an active destination worker; it will not be closed "
                    "concurrently",
                    backend_type,
                )
                continue
            try:
                backend.close()
            except Exception as error:
                _LOGGER.warning("Display backend %s cleanup failed: %s", backend_type, error)

    @staticmethod
    def _close_images(images: Mapping[ResolvedOutputSpecification, Image.Image]) -> None:
        for image in images.values():
            image.close()

    def _release(self, presentation: _Presentation | None) -> None:
        if presentation is None:
            return
        presentation.references -= 1
        if presentation.references == 0:
            try:
                self._close_images(presentation.images)
            except Exception:
                _LOGGER.exception("Failed to release prepared presentation images")

    def _wait_before_retry(self, delay: float) -> bool:
        deadline = time.monotonic() + delay
        with self._condition:
            while not self._stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                self._condition.wait(remaining)
            return False

    def _get_backend(self, configuration: DisplayBackendConfiguration) -> DisplayBackend:
        backend_type = configuration.type
        with self._backend_locks[backend_type]:
            backend = self._backends.get(backend_type)
            if backend is None:
                backend = self._factory(configuration)
                self._backends[backend_type] = backend
            return backend

    @staticmethod
    def _update_destination(
        backend: DisplayBackend,
        configuration: DisplayBackendConfiguration,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
    ) -> None:
        if configuration.type == "image-server":
            update_output = getattr(backend, "update_output", None)
            if update_output is None:
                raise DisplayBackendError("image-server backend does not support named output updates")
            update_output(destination.identifier, image)
        else:
            backend.update(image)

    def _run_destination(self, state: _DestinationState) -> None:
        name = state.key
        retry_delay = 1.0
        while True:
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
                backend = self._get_backend(state.backend_configuration)
                image = presentation.images[state.destination.output_specification]
                with self._backend_locks[state.backend_configuration.type]:
                    self._update_destination(backend, state.backend_configuration, state.destination, image)
            except Exception as error:
                recoverable = isinstance(error, DisplayBackendError) and error.recoverable
                with self._condition:
                    state.error = str(error)
                    state.terminal = not recoverable or not self._retry
                    self._signal_all_unavailable()
                    self._condition.notify_all()
                if isinstance(error, DisplayBackendError):
                    _LOGGER.warning("Display destination %s update failed: %s", name, error)
                else:
                    _LOGGER.exception("Unexpected display destination %s update failure", name)
                if state.terminal:
                    with self._condition:
                        self._release(presentation)
                    return
                with self._condition:
                    self._release(presentation)
                if not self._wait_before_retry(retry_delay):
                    return
                retry_delay = min(_MAX_RETRY_DELAY, retry_delay * 2)
                continue

            with self._condition:
                state.successful_identity = presentation.identity
                state.successful_at = self._monotonic_clock()
                state.error = None
                self._condition.notify_all()
                self._release(presentation)
            _LOGGER.info("Display destination %s published presentation %s", name, presentation.identity)
            retry_delay = 1.0

    def _signal_all_unavailable(self) -> None:
        if self._all_unavailable_event is not None and all(state.terminal for state in self._states.values()):
            self._all_unavailable_event.set()


__all__ = ["DisplayPublicationCoordinator"]

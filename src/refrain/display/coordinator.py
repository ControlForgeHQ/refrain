"""Serialized publication workers for configured display backends."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Condition, Event, Thread
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
    references: int = 0


@dataclass
class _DestinationState:
    backend_configuration: DisplayBackendConfiguration
    destination: DisplayOutputConfiguration
    key: str
    desired_identity: tuple[int, int] | None = None
    pending: _Presentation | None = None
    active_identity: tuple[int, int] | None = None
    successful_identity: tuple[int, int] | None = None
    successful_at: float | None = None
    retry_at: float = 0.0
    retry_delay: float = 1.0
    terminal: bool = False
    error: str | None = None


def _destination_identifier(
    configuration: DisplayBackendConfiguration,
    destination: DisplayOutputConfiguration,
) -> str:
    if configuration.type == "image-server" or len(configuration.outputs) > 1:
        return f"{configuration.type}:{destination.identifier}"
    return configuration.type


class DisplayPublicationCoordinator:
    """Publish each destination's matching variant on its backend's worker."""

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
        self._states = {
            identifier: _DestinationState(configuration, destination, identifier)
            for configuration in configurations
            for destination in configuration.outputs
            for identifier in (_destination_identifier(configuration, destination),)
        }
        expected_destinations = sum(len(configuration.outputs) for configuration in configurations)
        if len(self._states) != expected_destinations:
            raise ValueError("configured display destinations must have unique canonical identifiers")
        self._states_by_backend = {
            configuration.type: tuple(
                state for state in self._states.values() if state.backend_configuration is configuration
            )
            for configuration in configurations
        }
        self._worker_configurations = configurations
        self._backends: dict[str, DisplayBackend] = {}
        self._threads = [
            Thread(
                target=self._run_backend,
                args=(configuration, self._states_by_backend[configuration.type]),
                name=f"refrain-display-{configuration.type}",
                daemon=True,
            )
            for configuration in configurations
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
            return next(iter(self._states.values())).desired_identity if self._states else None

    @property
    def destination_identifiers(self) -> tuple[str, ...]:
        """Return the canonical runtime identifiers owned by this coordinator."""
        with self._condition:
            return tuple(self._states)

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
        """Replace pending scheduled work; ownership transfers to the coordinator."""
        with self._condition:
            if self._stopping:
                self._close_images(images)
                raise RuntimeError("display publication coordinator is stopping")
            if self._states and all(state.desired_identity == identity for state in self._states.values()):
                self._close_images(images)
                return
            required = {state.destination.output_specification for state in self._states.values() if not state.terminal}
            if required - images.keys():
                self._close_images(images)
                raise ValueError(f"publication is missing output variants: {required - images.keys()}")

            presentation = _Presentation(identity, images)
            for state in self._states.values():
                state.desired_identity = identity
                if state.terminal:
                    continue
                self._release(state.pending)
                state.pending = presentation
                presentation.references += 1
                state.retry_at = 0.0
                state.retry_delay = 1.0
            if presentation.references == 0:
                self._release(presentation)
            self._condition.notify_all()

    def clear_desired(self) -> None:
        """Discard pending scheduled images without interrupting active updates."""
        with self._condition:
            for state in self._states.values():
                self._release(state.pending)
                state.pending = None
                state.desired_identity = None
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

    def close(self) -> tuple[Thread, ...]:
        """Stop requests and wait a bounded time without interrupting active backend calls."""
        with self._condition:
            self._stopping = True
            for state in self._states.values():
                self._release(state.pending)
                state.pending = None
                state.desired_identity = None
            self._condition.notify_all()
        deadline = time.monotonic() + _SHUTDOWN_TIMEOUT
        for thread in self._threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)
        active_threads = tuple(thread for thread in self._threads if thread.is_alive())
        active_backend_types = {
            configuration.type
            for configuration, thread in zip(
                self._worker_configurations,
                self._threads,
                strict=True,
            )
            if thread in active_threads
        }
        for backend_type in active_backend_types:
            _LOGGER.error(
                "Display backend %s worker did not stop within %.0f seconds; "
                "its active update will not be interrupted or closed concurrently",
                backend_type,
                _SHUTDOWN_TIMEOUT,
            )
        return active_threads

    @staticmethod
    def _close_images(images: Mapping[ResolvedOutputSpecification, Image.Image]) -> None:
        closed: set[int] = set()
        for image in images.values():
            if id(image) in closed:
                continue
            closed.add(id(image))
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

    def _run_backend(
        self,
        configuration: DisplayBackendConfiguration,
        states: tuple[_DestinationState, ...],
    ) -> None:
        backend: DisplayBackend | None = None
        backend_retry_at = 0.0
        backend_retry_delay = 1.0
        try:
            while True:
                ready: _DestinationState | None = None
                presentation: _Presentation | None = None
                initialize_backend = False
                with self._condition:
                    while True:
                        if self._stopping:
                            return
                        now = time.monotonic()
                        eligible = next(
                            (
                                state
                                for state in states
                                if not state.terminal and state.pending is not None and state.retry_at <= now
                            ),
                            None,
                        )
                        if backend is None and eligible is not None and now >= backend_retry_at:
                            initialize_backend = True
                            break
                        if backend is not None and eligible is not None:
                            ready = eligible
                            presentation = ready.pending
                            assert presentation is not None
                            ready.pending = None
                            ready.active_identity = presentation.identity
                            break
                        deadlines = [
                            state.retry_at
                            for state in states
                            if not state.terminal and state.pending is not None and state.retry_at > now
                        ]
                        if backend is None and backend_retry_at > now:
                            if any(state.pending is not None and not state.terminal for state in states):
                                deadlines.append(backend_retry_at)
                        timeout = min(deadlines) - now if deadlines else None
                        self._condition.wait(timeout)

                if initialize_backend:
                    try:
                        backend = self._factory(configuration)
                    except Exception as error:
                        recoverable = isinstance(error, DisplayBackendError) and error.recoverable and self._retry
                        with self._condition:
                            if recoverable:
                                backend_retry_at = time.monotonic() + backend_retry_delay
                                backend_retry_delay = min(_MAX_RETRY_DELAY, backend_retry_delay * 2)
                            for state in states:
                                if state.terminal:
                                    continue
                                state.error = str(error)
                                state.terminal = not recoverable
                                if state.terminal:
                                    self._release(state.pending)
                                    state.pending = None
                                if state.pending is not None:
                                    state.retry_at = backend_retry_at
                            self._signal_all_unavailable()
                            self._condition.notify_all()
                        if isinstance(error, DisplayBackendError):
                            _LOGGER.warning("Display backend %s initialization failed: %s", configuration.type, error)
                        else:
                            _LOGGER.exception(
                                "Unexpected display backend %s initialization failure", configuration.type
                            )
                        if not recoverable:
                            return
                        continue

                    with self._condition:
                        self._backends[configuration.type] = backend
                        if self._stopping:
                            self._condition.notify_all()
                            return
                    backend_retry_at = 0.0
                    backend_retry_delay = 1.0
                    continue

                assert ready is not None and presentation is not None and backend is not None
                try:
                    image = presentation.images[ready.destination.output_specification]
                    backend.publish(ready.destination, image)
                except Exception as error:
                    recoverable = isinstance(error, DisplayBackendError) and error.recoverable and self._retry
                    with self._condition:
                        ready.active_identity = None
                        ready.error = str(error)
                        ready.terminal = not recoverable
                        if recoverable and ready.pending is None and ready.desired_identity == presentation.identity:
                            ready.pending = presentation
                            ready.retry_at = time.monotonic() + ready.retry_delay
                            ready.retry_delay = min(_MAX_RETRY_DELAY, ready.retry_delay * 2)
                        else:
                            self._release(presentation)
                        if ready.terminal:
                            self._release(ready.pending)
                            ready.pending = None
                        self._signal_all_unavailable()
                        self._condition.notify_all()
                        all_terminal = all(state.terminal for state in states)
                    if isinstance(error, DisplayBackendError):
                        _LOGGER.warning("Display destination %s update failed: %s", ready.key, error)
                    else:
                        _LOGGER.exception("Unexpected display destination %s update failure", ready.key)
                    if all_terminal:
                        return
                    continue

                with self._condition:
                    ready.active_identity = None
                    ready.successful_identity = presentation.identity
                    ready.successful_at = self._monotonic_clock()
                    ready.error = None
                    ready.retry_at = 0.0
                    ready.retry_delay = 1.0
                    self._condition.notify_all()
                    self._release(presentation)
                _LOGGER.info("Display destination %s published presentation %s", ready.key, presentation.identity)
        finally:
            if backend is not None:
                self._backends.pop(configuration.type, None)
                self._close_backend(configuration.type, backend)

    @staticmethod
    def _close_backend(backend_type: str, backend: DisplayBackend) -> None:
        try:
            backend.close()
        except Exception as error:
            _LOGGER.warning("Display backend %s cleanup failed: %s", backend_type, error)

    def _signal_all_unavailable(self) -> None:
        if self._all_unavailable_event is not None and all(state.terminal for state in self._states.values()):
            self._all_unavailable_event.set()


__all__ = ["DisplayPublicationCoordinator"]

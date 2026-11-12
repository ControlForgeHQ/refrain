"""Serialized publication workers for configured display backends."""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Condition, Event, Thread
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from PIL import Image

from ..config import DisplayBackendConfiguration, DisplayOutputConfiguration
from ..geometry import ResolvedOutputSpecification
from . import DisplayBackend, DisplayBackendError, create_display_backend

_LOGGER = logging.getLogger(__name__)
_MAX_RETRY_DELAY = 60.0
_SHUTDOWN_TIMEOUT = 60.0


class StagedTransientImages(dict[ResolvedOutputSpecification, Path]):
    """Request-owned validated PNG files, decoded only by active workers."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=False)


@dataclass
class _Presentation:
    identity: tuple[int, int]
    images: Mapping[ResolvedOutputSpecification, Image.Image]
    references: int = 1


class PublicationStatus(str, Enum):
    """Terminal or in-progress outcome for a one-shot publication request."""

    ACCEPTED = "accepted"
    SUCCEEDED = "succeeded"
    BUSY = "busy"
    INVALID = "invalid"
    DESTINATION_NOT_FOUND = "destination-not-found"
    UNSUPPORTED = "unsupported"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"
    STOPPING = "stopping"


@dataclass(frozen=True)
class PublicationResult:
    """Deterministic status and per-destination outcomes for a publication request."""

    status: PublicationStatus
    destinations: Mapping[str, tuple[bool | None, str | None]]


class PublicationOperation:
    """A one-shot publication request whose result can be observed while it runs."""

    def __init__(self, result: PublicationResult, *, done: bool = False) -> None:
        self._result = result
        self._done = Event()
        if done:
            self._done.set()

    @property
    def result(self) -> PublicationResult:
        return self._result

    def wait(self, timeout: float | None = None) -> PublicationResult:
        """Wait for a terminal result, or return the accepted result on timeout."""
        self._done.wait(timeout)
        return self._result

    def _complete(self, result: PublicationResult) -> None:
        self._result = result
        self._done.set()

    def _update(self, result: PublicationResult) -> None:
        self._result = result


@dataclass
class _OneShotPublication:
    operation: PublicationOperation
    identity: tuple[int, int] | None
    images: Mapping[ResolvedOutputSpecification, Image.Image] | StagedTransientImages
    destinations: tuple[str, ...]
    outcomes: dict[str, tuple[bool, str | None]]
    retry_at: dict[str, float]
    retry_delay: dict[str, float]
    forced: bool


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
    withdrawn: bool = False
    transient_supported: bool = True
    one_shot: _OneShotPublication | None = None
    one_shot_active: bool = False


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
        transient_capabilities: Mapping[str, bool] | None = None,
    ) -> None:
        self._condition = Condition()
        self._factory = backend_factory or self._default_factory
        self._retry = retry
        self._all_unavailable_event = all_unavailable_event
        self._monotonic_clock = monotonic_clock
        self._stopping = False
        self._draining = False
        self._states = {
            identifier: _DestinationState(configuration, destination, identifier)
            for configuration in configurations
            for destination in configuration.outputs
            for identifier in (_destination_identifier(configuration, destination),)
        }
        expected_destinations = sum(len(configuration.outputs) for configuration in configurations)
        if len(self._states) != expected_destinations:
            raise ValueError("configured display destinations must have unique canonical identifiers")
        for identifier, supported in (transient_capabilities or {}).items():
            if identifier not in self._states:
                raise ValueError(f"unknown display destination {identifier!r}")
            self._states[identifier].transient_supported = bool(supported)
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
            participating = [state for state in self._states.values() if not state.withdrawn]
            return bool(participating) and all(state.terminal for state in participating)

    @property
    def acknowledgements(self) -> dict[str, tuple[int, int] | None]:
        with self._condition:
            return {key: state.successful_identity for key, state in self._states.items()}

    @property
    def destination_statuses(self) -> tuple[dict[str, object], ...]:
        """Return configured destination capability and participation status."""
        with self._condition:
            return tuple(self._destination_status(key, state) for key, state in self._states.items())

    @staticmethod
    def _destination_status(key: str, state: _DestinationState) -> dict[str, object]:
        return {
            "identifier": key,
            "output_specification": state.destination.output_specification,
            "supports_transient": state.transient_supported,
            "participating": not state.withdrawn,
            "withdrawn": state.withdrawn,
            "available": not state.terminal and state.error is None,
        }

    def iter_destination_statuses(self) -> Iterator[dict[str, object]]:
        """Snapshot each destination separately without retaining a second full inventory."""
        for key, state in self._states.items():
            with self._condition:
                record = self._destination_status(key, state)
            yield record

    def publish(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification, Image.Image],
    ) -> None:
        """Replace pending scheduled work; ownership transfers to the coordinator."""
        with self._condition:
            if self._stopping or self._draining:
                self._close_images(images)
                raise RuntimeError("display publication coordinator is stopping")
            if self._states and all(state.desired_identity == identity for state in self._states.values()):
                self._close_images(images)
                return
            required = {
                state.destination.output_specification
                for state in self._states.values()
                if not state.terminal and not state.withdrawn
            }
            if required - images.keys():
                self._close_images(images)
                raise ValueError(f"publication is missing output variants: {required - images.keys()}")

            presentation = _Presentation(identity, images)
            for state in self._states.values():
                state.desired_identity = identity
                if state.terminal or state.withdrawn:
                    continue
                self._release(state.pending)
                state.pending = presentation
                presentation.references += 1
                state.retry_at = 0.0
                state.retry_delay = 1.0
            self._release(presentation)
            self._condition.notify_all()

    def withdraw_destination(self, identifier: str) -> bool:
        """Withdraw a configured destination for the rest of this runtime."""
        with self._condition:
            state = self._states.get(identifier)
            if state is None or state.withdrawn:
                return False
            state.withdrawn = True
            self._release(state.pending)
            state.pending = None
            self._condition.notify_all()
            return True

    def publish_transient(
        self,
        destinations: Iterable[str] | str,
        output_specifications: Mapping[str, ResolvedOutputSpecification],
        images: Mapping[ResolvedOutputSpecification, Image.Image] | StagedTransientImages,
    ) -> PublicationOperation:
        """Atomically admit complete caller-prepared images to selected destinations.

        Ownership of all supplied images transfers to the coordinator on entry,
        including when validation or admission fails.
        """
        with self._condition:
            selected, error = self._resolve_destinations(destinations)
            if error is not None:
                self._close_images(images)
                return self._rejected_operation(error, selected)
            assert selected is not None
            for key in selected:
                state = self._states[key]
                if state.withdrawn:
                    self._close_images(images)
                    return self._rejected_operation(PublicationStatus.WITHDRAWN, selected)
                if not state.transient_supported:
                    self._close_images(images)
                    return self._rejected_operation(PublicationStatus.UNSUPPORTED, selected)
            validation = self._validate_one_shot(selected, output_specifications, images)
            if validation is not None:
                self._close_images(images)
                return self._rejected_operation(validation, selected)
            if self._stopping or self._draining:
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STOPPING, selected)
            if self._backend_busy(selected):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.BUSY, selected)
            return self._admit_one_shot(selected, images, identity=None, forced=False)

    def force_scheduled_publication(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification, Image.Image],
    ) -> PublicationOperation:
        """Republish the current scheduled identity to participants.

        Ownership of supplied images transfers to the coordinator on entry,
        including when validation or admission fails.
        """
        with self._condition:
            selected = tuple(key for key, state in self._states.items() if not state.withdrawn)
            if not selected:
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if any(self._states[key].desired_identity != identity for key in selected):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if not isinstance(images, Mapping):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            required = {self._states[key].destination.output_specification for key in selected}
            if required - images.keys():
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if any(
                not isinstance(images[specification], Image.Image)
                or images[specification].size != specification.requested_output_size
                for specification in required
            ):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if self._stopping or self._draining:
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STOPPING, selected)
            if self._backend_busy(selected):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.BUSY, selected)
            return self._admit_one_shot(selected, images, identity=identity, forced=True)

    def _resolve_destinations(
        self,
        destinations: Iterable[str] | str,
    ) -> tuple[tuple[str, ...] | None, PublicationStatus | None]:
        if isinstance(destinations, str):
            selected = (
                tuple(key for key, state in self._states.items() if not state.withdrawn)
                if destinations == "all"
                else (destinations,)
            )
        else:
            try:
                selected = tuple(destinations)
            except TypeError:
                return None, PublicationStatus.INVALID
        if not selected or any(not isinstance(key, str) for key in selected):
            return selected, PublicationStatus.INVALID
        if len(set(selected)) != len(selected):
            return selected, PublicationStatus.INVALID
        if any(key not in self._states for key in selected):
            return selected, PublicationStatus.DESTINATION_NOT_FOUND
        return selected, None

    def _validate_one_shot(
        self,
        destinations: tuple[str, ...],
        output_specifications: Mapping[str, ResolvedOutputSpecification],
        images: Mapping[ResolvedOutputSpecification, Image.Image] | StagedTransientImages,
    ) -> PublicationStatus | None:
        if not isinstance(output_specifications, Mapping) or not isinstance(images, Mapping):
            return PublicationStatus.INVALID
        for key in destinations:
            state = self._states[key]
            specification = state.destination.output_specification
            if key not in output_specifications or output_specifications[key] != specification:
                return PublicationStatus.INVALID
            if specification not in images:
                return PublicationStatus.INVALID
            if not isinstance(images, StagedTransientImages):
                image = images[specification]
                if not isinstance(image, Image.Image) or image.size != specification.requested_output_size:
                    return PublicationStatus.INVALID
        return None

    def _backend_busy(self, destinations: tuple[str, ...]) -> bool:
        backend_types = {self._states[key].backend_configuration.type for key in destinations}
        for state in self._states.values():
            if state.backend_configuration.type not in backend_types:
                continue
            if state.active_identity is not None or state.pending is not None or state.one_shot is not None:
                return True
            if (
                not state.terminal
                and not state.withdrawn
                and state.desired_identity is not None
                and state.desired_identity != state.successful_identity
            ):
                return True
        return False

    @staticmethod
    def _publication_result(
        status: PublicationStatus,
        destinations: Iterable[str],
    ) -> PublicationResult:
        return PublicationResult(
            status,
            MappingProxyType({key: (None, None) for key in destinations if isinstance(key, str)}),
        )

    def _rejected_operation(
        self,
        status: PublicationStatus,
        destinations: Iterable[str] | None,
    ) -> PublicationOperation:
        keys = () if destinations is None else destinations
        return PublicationOperation(self._publication_result(status, keys), done=True)

    def _admit_one_shot(
        self,
        destinations: tuple[str, ...],
        images: Mapping[ResolvedOutputSpecification, Image.Image] | StagedTransientImages,
        *,
        identity: tuple[int, int] | None,
        forced: bool,
    ) -> PublicationOperation:
        if isinstance(images, StagedTransientImages):
            owned_images = images
        else:
            specifications = {self._states[key].destination.output_specification for key in destinations}
            owned_images = {specification: images[specification] for specification in specifications}
            used_image_ids = {id(image) for image in owned_images.values()}
            self._close_images(
                {specification: image for specification, image in images.items() if id(image) not in used_image_ids}
            )
            owned_images = MappingProxyType(owned_images)
        operation = PublicationOperation(self._publication_result(PublicationStatus.ACCEPTED, destinations))
        one_shot = _OneShotPublication(
            operation=operation,
            identity=identity,
            images=owned_images,
            destinations=destinations,
            outcomes={},
            retry_at={key: 0.0 for key in destinations},
            retry_delay={key: 1.0 for key in destinations},
            forced=forced,
        )
        for key in destinations:
            state = self._states[key]
            state.one_shot = one_shot
            if state.terminal:
                one_shot.outcomes[key] = (False, state.error or "destination is unavailable")
        self._complete_one_shot_if_ready(one_shot)
        self._condition.notify_all()
        return operation

    def _complete_one_shot_if_ready(self, operation: _OneShotPublication) -> None:
        if len(operation.outcomes) != len(operation.destinations):
            return
        status = (
            PublicationStatus.SUCCEEDED
            if all(success for success, _error in operation.outcomes.values())
            else PublicationStatus.FAILED
        )
        destinations = MappingProxyType({key: operation.outcomes[key] for key in operation.destinations})
        for key in operation.destinations:
            if self._states[key].one_shot is operation:
                self._states[key].one_shot = None
        try:
            self._close_images(operation.images)
        except Exception:
            _LOGGER.exception("Failed to release one-shot publication images")
        operation.operation._complete(PublicationResult(status, destinations))
        self._condition.notify_all()

    def _record_one_shot_result(
        self,
        state: _DestinationState,
        operation: _OneShotPublication,
        *,
        success: bool,
        error: str | None = None,
    ) -> None:
        operation.outcomes[state.key] = (success, error)
        if success:
            state.error = None
            if operation.forced and state.desired_identity == operation.identity:
                state.successful_identity = operation.identity
                state.successful_at = self._monotonic_clock()
        else:
            state.error = error
        operation.operation._update(
            PublicationResult(
                PublicationStatus.ACCEPTED,
                MappingProxyType({key: operation.outcomes.get(key, (None, None)) for key in operation.destinations}),
            )
        )
        self._complete_one_shot_if_ready(operation)

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
            participating = tuple(state for state in self._states.values() if not state.withdrawn)
            while any(state.successful_identity != identity and not state.terminal for state in participating):
                if self._draining or self._stopping:
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._condition.wait(remaining)
            return any(state.successful_identity == identity for state in participating)

    def has_successful_publication(self, identity: tuple[int, int]) -> bool:
        with self._condition:
            return any(not state.withdrawn and state.successful_identity == identity for state in self._states.values())

    def publication_results(self, identity: tuple[int, int]) -> dict[str, tuple[bool, str | None]]:
        with self._condition:
            return {
                key: (
                    state.successful_identity == identity,
                    (
                        None
                        if state.successful_identity == identity
                        else ("destination was withdrawn" if state.withdrawn else state.error)
                    ),
                )
                for key, state in self._states.items()
            }

    def first_successful_publication_time(self, identity: tuple[int, int]) -> float | None:
        with self._condition:
            times = [
                state.successful_at
                for state in self._states.values()
                if not state.withdrawn and state.successful_identity == identity and state.successful_at is not None
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
            participating = tuple(state for state in self._states.values() if not state.withdrawn)
            while not any(state.successful_identity == identity for state in participating):
                if self._draining or self._stopping:
                    break
                if all(state.terminal for state in participating):
                    break
                if cancellation_event is not None and cancellation_event.is_set():
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                if cancellation_event is not None:
                    remaining = 0.25 if remaining is None else min(remaining, 0.25)
                self._condition.wait(remaining)
            return any(state.successful_identity == identity for state in participating)

    def begin_draining(self) -> None:
        """Stop retries and new work while admitted, unattempted destinations finish."""
        with self._condition:
            self._draining = True
            for state in self._states.values():
                self._release(state.pending)
                state.pending = None
                operation = state.one_shot
                if (
                    operation is not None
                    and state.key not in operation.outcomes
                    and not state.one_shot_active
                    and operation.retry_at[state.key] > 0
                ):
                    self._record_one_shot_result(
                        state, operation, success=False, error=state.error or "coordinator is draining"
                    )
            self._condition.notify_all()

    def wait_for_drain(self) -> None:
        """Wait for admitted one-shot operations to reach terminal results."""
        with self._condition:
            while any(state.one_shot is not None for state in self._states.values()):
                self._condition.wait()

    def close(self) -> tuple[Thread, ...]:
        """Stop requests and wait a bounded time without interrupting active backend calls."""
        with self._condition:
            self._stopping = True
            operations: set[int] = set()
            for state in self._states.values():
                self._release(state.pending)
                state.pending = None
                state.desired_identity = None
                operation = state.one_shot
                if operation is None or id(operation) in operations:
                    continue
                operations.add(id(operation))
                for key in operation.destinations:
                    destination_state = self._states[key]
                    if key not in operation.outcomes and not destination_state.one_shot_active:
                        self._record_one_shot_result(
                            destination_state,
                            operation,
                            success=False,
                            error="coordinator is stopping",
                        )
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
    def _close_images(images: Mapping[ResolvedOutputSpecification, Image.Image] | StagedTransientImages) -> None:
        if isinstance(images, StagedTransientImages):
            # The request handler retains the global slot until staging is deleted.
            return
        if not isinstance(images, Mapping):
            return
        closed: set[int] = set()
        for image in images.values():
            if id(image) in closed:
                continue
            closed.add(id(image))
            if isinstance(image, Image.Image):
                try:
                    image.close()
                except Exception:
                    _LOGGER.exception("Failed to close a caller-owned publication image")

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
                one_shot: _OneShotPublication | None = None
                initialize_backend = False
                with self._condition:
                    while True:
                        if self._stopping:
                            return
                        now = time.monotonic()
                        one_shot_ready = next(
                            (
                                state
                                for state in states
                                if state.one_shot is not None
                                and state.key not in state.one_shot.outcomes
                                and not state.terminal
                                and state.one_shot.retry_at[state.key] <= now
                            ),
                            None,
                        )
                        one_shot_barrier = any(state.one_shot is not None for state in states)
                        eligible = next(
                            (
                                state
                                for state in states
                                if not one_shot_barrier
                                and not state.terminal
                                and not state.withdrawn
                                and state.pending is not None
                                and state.retry_at <= now
                            ),
                            None,
                        )
                        selected_state = one_shot_ready or eligible
                        if (
                            backend is None
                            and selected_state is not None
                            and (self._draining or now >= backend_retry_at)
                        ):
                            initialize_backend = True
                            break
                        if backend is not None and selected_state is not None:
                            ready = selected_state
                            if ready.one_shot is not None and ready.key not in ready.one_shot.outcomes:
                                one_shot = ready.one_shot
                                ready.one_shot_active = True
                            else:
                                presentation = ready.pending
                                assert presentation is not None
                                ready.pending = None
                                ready.active_identity = presentation.identity
                            break
                        deadlines = [
                            state.retry_at
                            for state in states
                            if not state.terminal
                            and state.pending is not None
                            and state.one_shot is None
                            and not state.withdrawn
                            and state.retry_at > now
                        ]
                        deadlines.extend(
                            state.one_shot.retry_at[state.key]
                            for state in states
                            if state.one_shot is not None
                            and state.key not in state.one_shot.outcomes
                            and not state.terminal
                            and state.one_shot.retry_at[state.key] > now
                        )
                        if backend is None and backend_retry_at > now:
                            if any(
                                (state.pending is not None or state.one_shot is not None) and not state.terminal
                                for state in states
                            ):
                                deadlines.append(backend_retry_at)
                        timeout = min(deadlines) - now if deadlines else None
                        self._condition.wait(timeout)

                if initialize_backend:
                    try:
                        backend = self._factory(configuration)
                    except Exception as error:
                        recoverable = isinstance(error, DisplayBackendError) and error.recoverable and self._retry
                        with self._condition:
                            retry = recoverable and not self._stopping and not self._draining
                            if retry:
                                backend_retry_at = time.monotonic() + backend_retry_delay
                                backend_retry_delay = min(_MAX_RETRY_DELAY, backend_retry_delay * 2)
                            for state in states:
                                pending_one_shot = (
                                    state.one_shot is not None and state.key not in state.one_shot.outcomes
                                )
                                if (state.terminal or state.withdrawn) and not pending_one_shot:
                                    continue
                                state.error = str(error)
                                state.terminal = not recoverable
                                if state.terminal:
                                    self._release(state.pending)
                                    state.pending = None
                                if pending_one_shot:
                                    operation = state.one_shot
                                    if retry:
                                        operation.retry_at[state.key] = backend_retry_at
                                        operation.retry_delay[state.key] = min(
                                            _MAX_RETRY_DELAY,
                                            operation.retry_delay[state.key] * 2,
                                        )
                                    else:
                                        self._record_one_shot_result(
                                            state,
                                            operation,
                                            success=False,
                                            error=str(error),
                                        )
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

                assert ready is not None and backend is not None
                try:
                    if one_shot is not None and isinstance(one_shot.images, StagedTransientImages):
                        with closing(
                            Image.open(one_shot.images[ready.destination.output_specification], formats=["PNG"])
                        ) as image:
                            image.load()
                            backend.publish(ready.destination, image)
                    elif one_shot is not None:
                        image = one_shot.images[ready.destination.output_specification]
                        backend.publish(ready.destination, image)
                    else:
                        assert presentation is not None
                        image = presentation.images[ready.destination.output_specification]
                        backend.publish(ready.destination, image)
                except Exception as error:
                    recoverable = isinstance(error, DisplayBackendError) and error.recoverable and self._retry
                    with self._condition:
                        retry = recoverable and not self._stopping and not self._draining
                        ready.error = str(error)
                        ready.terminal = not recoverable
                        if one_shot is not None:
                            ready.one_shot_active = False
                            if retry:
                                one_shot.retry_at[ready.key] = time.monotonic() + one_shot.retry_delay[ready.key]
                                one_shot.retry_delay[ready.key] = min(
                                    _MAX_RETRY_DELAY,
                                    one_shot.retry_delay[ready.key] * 2,
                                )
                            else:
                                self._record_one_shot_result(
                                    ready,
                                    one_shot,
                                    success=False,
                                    error=str(error),
                                )
                        else:
                            ready.active_identity = None
                            assert presentation is not None
                            if (
                                retry
                                and ready.pending is None
                                and ready.desired_identity == presentation.identity
                                and not ready.withdrawn
                            ):
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
                    if one_shot is not None:
                        ready.one_shot_active = False
                        one_shot.retry_at[ready.key] = 0.0
                        one_shot.retry_delay[ready.key] = 1.0
                        self._record_one_shot_result(ready, one_shot, success=True)
                    else:
                        ready.active_identity = None
                        assert presentation is not None
                        ready.successful_identity = presentation.identity
                        ready.successful_at = self._monotonic_clock()
                        ready.error = None
                        ready.retry_at = 0.0
                        ready.retry_delay = 1.0
                    self._condition.notify_all()
                    if presentation is not None:
                        self._release(presentation)
                published_identity = (
                    one_shot.identity
                    if one_shot is not None
                    else presentation.identity if presentation is not None else None
                )
                _LOGGER.info("Display destination %s published presentation %s", ready.key, published_identity)
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
        participating = [state for state in self._states.values() if not state.withdrawn]
        if self._all_unavailable_event is not None and participating and all(state.terminal for state in participating):
            self._all_unavailable_event.set()


__all__ = [
    "DisplayPublicationCoordinator",
    "PublicationOperation",
    "PublicationResult",
    "PublicationStatus",
]

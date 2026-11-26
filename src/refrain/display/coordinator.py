"""Serialized publication workers for configured display backends."""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from threading import Condition, Event, Thread
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from PIL import Image

from ..config import (
    DisplayBackendConfiguration,
    DisplayOutputConfiguration,
    PreparedImageVariantKey,
)
from ..geometry import ResolvedOutputSpecification
from ..publication_storage import PublicationStorageError
from . import (
    DisplayBackend,
    DisplayBackendError,
    DisplayBackendUpdateError,
    PublicationDisplayBackend,
    WithdrawableDisplayBackend,
    create_display_backend,
)

_LOGGER = logging.getLogger(__name__)
_MAX_RETRY_DELAY = 60.0
_MAX_RETRY_ATTEMPTS = 5
_SHUTDOWN_TIMEOUT = 60.0


class StagedTransientImages(dict[ResolvedOutputSpecification, Path]):
    """Request-owned validated PNG files, decoded only by active workers."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self.destination_paths: dict[str, Path] | None = None
        self.audiences: dict[str, str] | None = None

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=False)


@dataclass
class _Presentation:
    identity: tuple[int, int]
    images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image]
    metadata: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, dict[str, object]] | None = None
    transient: bool = False
    allow_missing: bool = False
    references: int = 1
    destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None


class PublicationStatus(str, Enum):
    """Terminal or in-progress outcome for a one-shot publication request."""

    ACCEPTED = "accepted"
    SUCCEEDED = "succeeded"
    BUSY = "busy"
    INVALID = "invalid"
    NO_TARGET = "no-target"
    STALE_PRESENTATION = "stale-presentation"
    DESTINATION_NOT_FOUND = "destination-not-found"
    UNSUPPORTED = "unsupported"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"
    UNCONFIRMED = "unconfirmed"
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
    images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image] | StagedTransientImages
    metadata: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, dict[str, object]] | None
    destinations: tuple[str, ...]
    outcomes: dict[str, tuple[bool | None, str | None]]
    retry_at: dict[str, float]
    retry_delay: dict[str, float]
    retry_attempts: dict[str, int]
    forced: bool
    destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None
    hold_date: date | None = None
    hold_expired: bool = False


@dataclass
class _DestinationState:
    backend_configuration: DisplayBackendConfiguration
    destination: DisplayOutputConfiguration
    key: str
    desired_identity: tuple[int, int] | None = None
    desired_key: ResolvedOutputSpecification | PreparedImageVariantKey | None = None
    pending: _Presentation | None = None
    active_identity: tuple[int, int] | None = None
    preparation_error: str | None = None
    successful_identity: tuple[int, int] | None = None
    successful_at: float | None = None
    retry_at: float = 0.0
    retry_delay: float = 1.0
    retry_attempts: int = 0
    recoverable_failure: bool = False
    terminal: bool = False
    error: str | None = None
    withdrawn: bool = False
    transient_supported: bool = True
    one_shot: _OneShotPublication | None = None
    one_shot_active: bool = False
    hold_date: date | None = None
    expiry_pending: bool = False


class DisplayPublicationCoordinator:
    """Publish each destination's matching variant on its backend's worker."""

    def __init__(
        self,
        configurations: tuple[DisplayBackendConfiguration, ...],
        backend_factory: Callable[[DisplayBackendConfiguration], DisplayBackend] | None = None,
        *,
        retry: bool = True,
        all_unavailable_event: Event | None = None,
        all_withdrawn_event: Event | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        logical_date: Callable[[], date] | None = None,
        transient_capabilities: Mapping[str, bool] | None = None,
        publication_finalizer: (
            Callable[[DisplayOutputConfiguration, dict[str, object] | None], dict[str, object]] | None
        ) = None,
    ) -> None:
        self._condition = Condition()
        self._factory = backend_factory or self._default_factory
        self._retry = retry
        self._all_unavailable_event = all_unavailable_event
        self._all_withdrawn_event = all_withdrawn_event
        self._monotonic_clock = monotonic_clock
        self._logical_date = logical_date
        self._publication_finalizer = publication_finalizer
        self._stopping = False
        self._draining = False
        self._active_transient: _OneShotPublication | None = None
        self._states = {
            destination.identifier: _DestinationState(configuration, destination, destination.identifier)
            for configuration in configurations
            for destination in configuration.outputs
        }
        self._publication_metadata: dict[
            tuple[int, int],
            Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, dict[str, object]],
        ] = {}
        self._transient_presentations: set[tuple[int, int]] = set()
        expected_destinations = sum(len(configuration.outputs) for configuration in configurations)
        if len(self._states) != expected_destinations:
            raise ValueError("configured display destinations must have unique identifiers")
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
        return create_display_backend(configuration.type)

    @property
    def desired_identity(self) -> tuple[int, int] | None:
        with self._condition:
            return next(iter(self._states.values())).desired_identity if self._states else None

    @property
    def destination_identifiers(self) -> tuple[str, ...]:
        """Return the configured identifiers owned by this coordinator."""
        with self._condition:
            return tuple(self._states)

    @property
    def all_unavailable(self) -> bool:
        with self._condition:
            participating = [state for state in self._states.values() if not state.withdrawn]
            return bool(participating) and all(state.terminal for state in participating)

    @property
    def has_participating_destinations(self) -> bool:
        with self._condition:
            return any(not state.withdrawn for state in self._states.values())

    @property
    def acknowledgements(self) -> dict[str, tuple[int, int] | None]:
        with self._condition:
            return {key: state.successful_identity for key, state in self._states.items()}

    @property
    def destination_statuses(self) -> tuple[dict[str, object], ...]:
        """Return configured destination capability and participation status."""
        with self._condition:
            return tuple(self._destination_status(key, state) for key, state in self._states.items())

    def _destination_status(self, key: str, state: _DestinationState) -> dict[str, object]:
        backend = self._backends.get(state.backend_configuration.type)
        delivery_available = getattr(backend, "delivery_available", None)
        if state.backend_configuration.type == "publish":
            available = "unknown"
        elif isinstance(delivery_available, bool):
            available = delivery_available
        else:
            available = backend is not None and not state.terminal and state.error is None
        return {
            "identifier": key,
            "audience": state.destination.audience,
            "output_specification": state.destination.output_specification,
            "supports_transient": state.transient_supported,
            "participating": not state.withdrawn,
            "withdrawn": state.withdrawn,
            "available": available,
            "publication_accepted": (
                state.desired_identity is not None and state.successful_identity == state.desired_identity
            ),
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
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image],
        *,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
        _allow_missing: bool = False,
    ) -> None:
        """Replace pending scheduled work; ownership transfers to the coordinator."""
        with self._condition:
            metadata = self._publication_metadata.pop(identity, None)
            transient = identity in self._transient_presentations
            self._transient_presentations.discard(identity)
            if self._stopping or self._draining:
                self._close_images(images)
                raise RuntimeError("display publication coordinator is stopping")
            try:
                destination_keys = self._validated_destination_keys(destination_keys)
            except ValueError:
                self._close_images(images)
                raise
            if self._states and all(
                state.desired_identity == identity
                and state.desired_key == self._destination_key(state.destination, destination_keys)
                and (
                    state.preparation_error is None
                    or self._scheduled_image(images, state.destination, destination_keys) is None
                )
                for state in self._states.values()
            ):
                self._close_images(images)
                return
            if _allow_missing:
                self._renew_recovery(
                    state
                    for state in self._states.values()
                    if self._scheduled_image(images, state.destination, destination_keys) is not None
                    and not (
                        state.desired_identity == identity
                        and state.desired_key == self._destination_key(state.destination, destination_keys)
                        and state.preparation_error is None
                    )
                )
            else:
                self._renew_recovery(self._states.values())
            missing = {
                state.key
                for state in self._states.values()
                if (not state.terminal or _allow_missing)
                and not state.withdrawn
                and self._scheduled_image(images, state.destination, destination_keys) is None
            }
            if missing and not _allow_missing:
                self._close_images(images)
                raise ValueError(f"publication is missing output variants for destinations: {missing}")

            presentation = _Presentation(
                identity, images, metadata, transient, allow_missing=_allow_missing, destination_keys=destination_keys
            )
            for state in self._states.values():
                key = self._destination_key(state.destination, destination_keys)
                if (
                    _allow_missing
                    and state.desired_identity == identity
                    and state.desired_key == key
                    and state.preparation_error is None
                ):
                    continue
                if state.desired_identity == identity and state.desired_key != key:
                    state.successful_identity = None
                    state.successful_at = None
                state.desired_identity = identity
                state.desired_key = key
                state.preparation_error = (
                    "no prepared image is available for this destination" if state.key in missing else None
                )
                if state.key in missing:
                    self._release(state.pending)
                    state.pending = None
                    continue
                if state.terminal or state.withdrawn:
                    continue
                self._release(state.pending)
                state.pending = presentation
                presentation.references += 1
                state.retry_at = 0.0
                state.retry_delay = 1.0
            self._release(presentation)
            self._condition.notify_all()

    def publish_transient_presentation(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image],
        *,
        allow_missing: bool = False,
    ) -> None:
        """Publish a complete application-owned view through scheduled coordination."""
        with self._condition:
            self._transient_presentations.add(identity)
        try:
            if allow_missing:
                self.publish(identity, images, _allow_missing=True)
            else:
                self.publish(identity, images)
        finally:
            with self._condition:
                self._transient_presentations.discard(identity)

    def publish_with_metadata(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image],
        metadata: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, dict[str, object]],
        *,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
    ) -> None:
        """Publish scheduled images with the metadata from their prepared variants."""
        with self._condition:
            self._publication_metadata[identity] = metadata
            try:
                self.publish(identity, images, destination_keys=destination_keys)
            finally:
                self._publication_metadata.pop(identity, None)

    def withdraw_destination(self, identifier: str) -> bool:
        """Withdraw a configured destination for the rest of this runtime."""
        return self._withdraw_destinations((identifier,))

    def _withdraw_destinations(self, identifiers: Iterable[str]) -> bool:
        with self._condition:
            changed = False
            for identifier in identifiers:
                state = self._states.get(identifier)
                if state is None or state.withdrawn:
                    continue
                state.withdrawn = True
                self._release(state.pending)
                state.pending = None
                changed = True
                _LOGGER.info("Display destination %s withdrawn from publication for this runtime", identifier)
            if changed:
                self._signal_all_unavailable()
                if self._all_withdrawn_event is not None and all(state.withdrawn for state in self._states.values()):
                    self._all_withdrawn_event.set()
                self._condition.notify_all()
            return changed

    def publish_transient(
        self,
        destinations: Iterable[str] | str,
        output_specifications: Mapping[str, ResolvedOutputSpecification],
        images: Mapping[ResolvedOutputSpecification, Image.Image] | StagedTransientImages,
        *,
        all_day: bool = False,
    ) -> PublicationOperation:
        """Atomically admit complete caller-prepared images to selected destinations.

        Ownership of all supplied images transfers to the coordinator on entry,
        including when validation or admission fails.
        """
        with self._condition:
            if not isinstance(all_day, bool) or (all_day and self._logical_date is None):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, None)
            current_date = self._observe_logical_date()
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
            if self._active_transient is not None or self._backend_busy(selected):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.BUSY, selected)
            self._renew_recovery(self._states[key] for key in selected)
            return self._admit_one_shot(
                selected, images, identity=None, forced=False, hold_date=current_date if all_day else None
            )

    def force_scheduled_publication(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image],
        *,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
        expected_date: date | None = None,
        admission_check: Callable[[], bool] | None = None,
    ) -> PublicationOperation:
        """Republish the current scheduled identity to participants.

        Ownership of supplied images transfers to the coordinator on entry,
        including when validation or admission fails.
        """
        with self._condition:
            metadata = self._publication_metadata.pop(identity, None)
            selected = tuple(key for key, state in self._states.items() if not state.withdrawn)
            if not selected:
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.NO_TARGET, selected)
            if any(self._states[key].desired_identity != identity for key in selected):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STALE_PRESENTATION, selected)
            if not isinstance(images, Mapping):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if destination_keys is not None and (
                not isinstance(destination_keys, Mapping)
                or set(destination_keys) != set(self._states)
                or any(
                    not isinstance(key, (ResolvedOutputSpecification, PreparedImageVariantKey))
                    for key in destination_keys.values()
                )
            ):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if any(
                self._states[key].desired_key != self._destination_key(self._states[key].destination, destination_keys)
                for key in selected
            ):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STALE_PRESENTATION, selected)
            if destination_keys is not None and any(
                (prepared_key := destination_keys[key])
                != self._states[key].destination.prepared_image_key_for_qr(
                    prepared_key.qr_payload if isinstance(prepared_key, PreparedImageVariantKey) else None
                )
                for key in selected
            ):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STALE_PRESENTATION, selected)
            try:
                destination_keys = self._validated_destination_keys(destination_keys)
            except ValueError:
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if any(
                self._scheduled_image(images, self._states[key].destination, destination_keys) is None
                for key in selected
            ):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if any(
                not isinstance(
                    image := self._scheduled_image(images, self._states[key].destination, destination_keys), Image.Image
                )
                or image.size != self._states[key].destination.output_specification.requested_output_size
                for key in selected
            ):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.INVALID, selected)
            if self._stopping or self._draining:
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STOPPING, selected)
            if expected_date is not None and (self._logical_date is None or self._logical_date() != expected_date):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.STALE_PRESENTATION, selected)
            if admission_check is not None:
                try:
                    current = admission_check()
                except Exception:
                    self._close_images(images)
                    raise
                if not current:
                    self._close_images(images)
                    return self._rejected_operation(PublicationStatus.STALE_PRESENTATION, selected)
            if self._backend_busy(selected):
                self._close_images(images)
                return self._rejected_operation(PublicationStatus.BUSY, selected)
            self._renew_recovery(self._states[key] for key in selected)
            for state in self._states.values():
                state.hold_date = None
                state.expiry_pending = False
            return self._admit_one_shot(
                selected, images, identity=identity, forced=True, metadata=metadata, destination_keys=destination_keys
            )

    def force_scheduled_publication_with_metadata(
        self,
        identity: tuple[int, int],
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image],
        metadata: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, dict[str, object]],
        *,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
        expected_date: date | None = None,
        admission_check: Callable[[], bool] | None = None,
    ) -> PublicationOperation:
        """Force scheduled publication with the metadata from its prepared variants."""
        with self._condition:
            self._publication_metadata[identity] = metadata
            try:
                return self.force_scheduled_publication(
                    identity,
                    images,
                    destination_keys=destination_keys,
                    expected_date=expected_date,
                    admission_check=admission_check,
                )
            finally:
                self._publication_metadata.pop(identity, None)

    @staticmethod
    def _destination_key(
        destination: DisplayOutputConfiguration,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
    ) -> ResolvedOutputSpecification | PreparedImageVariantKey:
        return destination.prepared_image_key if destination_keys is None else destination_keys[destination.identifier]

    @classmethod
    def _scheduled_image(
        cls,
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image],
        destination: DisplayOutputConfiguration,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
    ) -> Image.Image | None:
        """Return the image for one destination's preparation-group variant."""
        return images.get(cls._destination_key(destination, destination_keys))

    def _validated_destination_keys(
        self, destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None
    ) -> Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None:
        if destination_keys is None:
            return None
        if not isinstance(destination_keys, Mapping) or set(destination_keys) != set(self._states):
            raise ValueError("destination preparation keys must identify every configured destination")
        for identifier, key in destination_keys.items():
            destination = self._states[identifier].destination
            payload = key.qr_payload if isinstance(key, PreparedImageVariantKey) else None
            if key != destination.prepared_image_key_for_qr(payload):
                raise ValueError(f"invalid preparation key for destination {identifier!r}")
        return MappingProxyType(dict(destination_keys))

    def _resolve_destinations(
        self,
        destinations: Iterable[str] | str,
    ) -> tuple[tuple[str, ...] | None, PublicationStatus | None]:
        if isinstance(destinations, str):
            selected = (
                tuple(key for key, state in self._states.items() if not state.withdrawn)
                if destinations == "@all"
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
        if isinstance(images, StagedTransientImages):
            if (
                images.destination_paths is None
                or images.audiences is None
                or set(images.destination_paths) != set(destinations)
                or set(images.audiences) != set(destinations)
            ):
                return PublicationStatus.INVALID
        for key in destinations:
            state = self._states[key]
            specification = state.destination.output_specification
            if key not in output_specifications or output_specifications[key] != specification:
                return PublicationStatus.INVALID
            if isinstance(images, StagedTransientImages):
                assert images.destination_paths is not None and images.audiences is not None
                if key not in images.destination_paths or images.audiences[key] != state.destination.audience:
                    return PublicationStatus.INVALID
            elif specification not in images:
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
            if (
                state.active_identity is not None
                or (state.pending is not None and state.hold_date is None and not state.expiry_pending)
                or state.one_shot is not None
            ):
                return True
            if (
                not state.terminal
                and not state.withdrawn
                and state.hold_date is None
                and not state.expiry_pending
                and state.preparation_error is None
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
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image] | StagedTransientImages,
        *,
        identity: tuple[int, int] | None,
        forced: bool,
        metadata: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, dict[str, object]] | None = None,
        destination_keys: Mapping[str, ResolvedOutputSpecification | PreparedImageVariantKey] | None = None,
        hold_date: date | None = None,
    ) -> PublicationOperation:
        if isinstance(images, StagedTransientImages):
            owned_images = images
        elif forced:
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
            metadata=metadata,
            destinations=destinations,
            outcomes={},
            retry_at={key: 0.0 for key in destinations},
            retry_delay={key: 1.0 for key in destinations},
            retry_attempts={key: 0 for key in destinations},
            forced=forced,
            destination_keys=destination_keys,
            hold_date=hold_date,
        )
        if not forced:
            self._active_transient = one_shot
        for key in destinations:
            state = self._states[key]
            state.one_shot = one_shot
            if state.terminal:
                one_shot.outcomes[key] = (False, state.error or "destination is unavailable")
                state.one_shot = None
        self._complete_one_shot_if_ready(one_shot)
        self._condition.notify_all()
        return operation

    def _complete_one_shot_if_ready(self, operation: _OneShotPublication) -> None:
        if len(operation.outcomes) != len(operation.destinations):
            return
        outcomes = [success for success, _error in operation.outcomes.values()]
        if all(success is True for success in outcomes):
            status = PublicationStatus.SUCCEEDED
        elif any(success is False for success in outcomes):
            status = PublicationStatus.FAILED
        else:
            status = PublicationStatus.UNCONFIRMED
        destinations = MappingProxyType({key: operation.outcomes[key] for key in operation.destinations})
        for key in operation.destinations:
            if self._states[key].one_shot is operation:
                self._states[key].one_shot = None
        if self._active_transient is operation:
            self._active_transient = None
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
        success: bool | None,
        error: str | None = None,
    ) -> None:
        current_date = self._observe_logical_date()
        operation.outcomes[state.key] = (success, error)
        if state.one_shot is operation:
            state.one_shot = None
        if success:
            state.error = None
            if not operation.forced:
                if operation.hold_date is None:
                    state.hold_date = None
                elif (
                    not self._stopping
                    and not self._draining
                    and not operation.hold_expired
                    and operation.hold_date == current_date
                ):
                    state.hold_date = operation.hold_date
            if (
                operation.forced
                and state.desired_identity == operation.identity
                and state.desired_key == self._destination_key(state.destination, operation.destination_keys)
            ):
                state.successful_identity = operation.identity
                state.successful_at = self._monotonic_clock()
                if (
                    state.pending is not None
                    and state.pending.identity == operation.identity
                    and self._destination_key(state.destination, state.pending.destination_keys) == state.desired_key
                ):
                    self._release(state.pending)
                    state.pending = None
        elif not state.withdrawn:
            state.error = error
        operation.operation._update(
            PublicationResult(
                PublicationStatus.ACCEPTED,
                MappingProxyType({key: operation.outcomes.get(key, (None, None)) for key in operation.destinations}),
            )
        )
        self._complete_one_shot_if_ready(operation)

    def expire_all_day_holds(self, expected_date: date) -> bool:
        """Release holds only when the reconciled date is still current."""
        with self._condition:
            current_date = self._observe_logical_date()
            if current_date != expected_date:
                return False
            for state in self._states.values():
                state.expiry_pending = False
            self._condition.notify_all()
            return True

    def _observe_logical_date(self) -> date | None:
        if self._logical_date is None:
            return None
        current_date = self._logical_date()
        for state in self._states.values():
            if state.hold_date is not None and state.hold_date != current_date:
                state.hold_date = None
                state.expiry_pending = True
            operation = state.one_shot
            if (
                operation is not None
                and operation.hold_date is not None
                and not operation.hold_expired
                and operation.hold_date != current_date
            ):
                operation.hold_expired = True
                for key in operation.destinations:
                    self._states[key].expiry_pending = True
        return current_date

    def clear_desired(self) -> None:
        """Discard pending scheduled images without interrupting active updates."""
        with self._condition:
            for state in self._states.values():
                self._release(state.pending)
                state.pending = None
                state.desired_identity = None
                state.desired_key = None
                state.preparation_error = None
            self._condition.notify_all()

    def wait_for_publication(self, identity: tuple[int, int], timeout: float | None = None) -> bool:
        """Wait until every destination succeeds or becomes terminal; return whether any succeeded."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while True:
                participating = tuple(state for state in self._states.values() if not state.withdrawn)
                if not any(
                    state.successful_identity != identity and not state.terminal and state.preparation_error is None
                    for state in participating
                ):
                    break
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
                        else (
                            "destination was withdrawn" if state.withdrawn else state.preparation_error or state.error
                        )
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
            while True:
                participating = tuple(state for state in self._states.values() if not state.withdrawn)
                if any(state.successful_identity == identity for state in participating):
                    break
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
                state.hold_date = None
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
                state.hold_date = None
                self._release(state.pending)
                state.pending = None
                state.desired_identity = None
                state.desired_key = None
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
    def _close_images(
        images: Mapping[ResolvedOutputSpecification | PreparedImageVariantKey, Image.Image] | StagedTransientImages,
    ) -> None:
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
        backend_retry_attempts = 0
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
                                and state.hold_date is None
                                and not state.expiry_pending
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
                            if backend_retry_attempts >= _MAX_RETRY_ATTEMPTS:
                                backend_retry_attempts = 0
                                backend_retry_delay = 1.0
                                backend_retry_at = 0.0
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
                            and state.hold_date is None
                            and not state.expiry_pending
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
                    backend_retry_attempts += 1
                    try:
                        backend = self._factory(configuration)
                        if isinstance(backend, WithdrawableDisplayBackend):
                            try:

                                def withdraw_backend() -> None:
                                    self._withdraw_destinations(state.key for state in states)

                                backend.set_withdrawal_callback(withdraw_backend)
                            except Exception:
                                self._close_backend(configuration.type, backend)
                                backend = None
                                raise
                    except Exception as error:
                        recoverable = isinstance(error, DisplayBackendError) and error.recoverable and self._retry
                        with self._condition:
                            retry = (
                                recoverable
                                and backend_retry_attempts < _MAX_RETRY_ATTEMPTS
                                and not self._stopping
                                and not self._draining
                            )
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
                                state.recoverable_failure = recoverable
                                state.retry_attempts = backend_retry_attempts if recoverable else 0
                                state.terminal = not retry
                                if state.terminal:
                                    if (
                                        state.pending is not None
                                        and state.pending.allow_missing
                                        and state.desired_identity == state.pending.identity
                                    ):
                                        state.preparation_error = "fallback image lost after backend failure"
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
                        continue

                    with self._condition:
                        self._backends[configuration.type] = backend
                        for state in states:
                            if not state.terminal:
                                state.retry_attempts = 0
                                state.recoverable_failure = False
                        if self._stopping:
                            self._condition.notify_all()
                            return
                    backend_retry_at = 0.0
                    backend_retry_delay = 1.0
                    backend_retry_attempts = 0
                    continue

                assert ready is not None and backend is not None
                try:
                    if one_shot is not None and isinstance(one_shot.images, StagedTransientImages):
                        assert one_shot.images.destination_paths is not None
                        staged_path = one_shot.images.destination_paths[ready.key]
                        with closing(Image.open(staged_path, formats=["PNG"])) as image:
                            image.load()
                            self._publish_backend_image(
                                backend,
                                ready.destination,
                                image,
                                transient=True,
                                publication_finalizer=self._publication_finalizer,
                            )
                    elif one_shot is not None:
                        image = (
                            self._scheduled_image(one_shot.images, ready.destination, one_shot.destination_keys)
                            if one_shot.forced
                            else one_shot.images[ready.destination.output_specification]
                        )
                        assert image is not None
                        prepared_metadata = (
                            None
                            if one_shot.metadata is None
                            else one_shot.metadata.get(
                                ready.destination.prepared_image_key
                                if one_shot.destination_keys is None
                                else one_shot.destination_keys[ready.key]
                            )
                        )
                        self._publish_backend_image(
                            backend,
                            ready.destination,
                            image,
                            prepared_metadata=prepared_metadata,
                            transient=not one_shot.forced,
                            publication_finalizer=self._publication_finalizer,
                        )
                    else:
                        assert presentation is not None
                        image = self._scheduled_image(
                            presentation.images, ready.destination, presentation.destination_keys
                        )
                        assert image is not None
                        prepared_metadata = (
                            None
                            if presentation.metadata is None
                            else presentation.metadata.get(
                                ready.destination.prepared_image_key
                                if presentation.destination_keys is None
                                else presentation.destination_keys[ready.key]
                            )
                        )
                        self._publish_backend_image(
                            backend,
                            ready.destination,
                            image,
                            prepared_metadata=prepared_metadata,
                            transient=presentation.transient,
                            publication_finalizer=self._publication_finalizer,
                        )
                except Exception as error:
                    cause = error.__cause__
                    uncertain = one_shot is not None and isinstance(cause, PublicationStorageError) and cause.published
                    recoverable = isinstance(error, DisplayBackendError) and error.recoverable and self._retry
                    with self._condition:
                        if one_shot is not None:
                            one_shot.retry_attempts[ready.key] += 1
                            ready.retry_attempts = one_shot.retry_attempts[ready.key]
                        else:
                            ready.retry_attempts += 1
                        ready.recoverable_failure = recoverable or uncertain
                        attempt = ready.retry_attempts
                        retry = (
                            recoverable
                            and not uncertain
                            and attempt < _MAX_RETRY_ATTEMPTS
                            and not self._stopping
                            and not self._draining
                        )
                        if not ready.withdrawn:
                            ready.error = str(error)
                            ready.terminal = not retry
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
                                    success=None if uncertain else False,
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
                            if (
                                ready.pending is not None
                                and ready.pending.allow_missing
                                and ready.desired_identity == ready.pending.identity
                            ):
                                ready.preparation_error = "fallback image lost after backend failure"
                            if (
                                one_shot is None
                                and presentation is not None
                                and presentation.allow_missing
                                and ready.pending is None
                                and ready.desired_identity == presentation.identity
                            ):
                                ready.preparation_error = "fallback image lost after backend failure"
                            self._release(ready.pending)
                            ready.pending = None
                        self._signal_all_unavailable()
                        self._condition.notify_all()
                    if isinstance(error, DisplayBackendError):
                        _LOGGER.warning("Display destination %s update failed: %s", ready.key, error)
                    else:
                        _LOGGER.exception("Unexpected display destination %s update failure", ready.key)
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
                        if (
                            ready.desired_identity != presentation.identity
                            or ready.desired_key
                            == self._destination_key(ready.destination, presentation.destination_keys)
                        ):
                            ready.successful_identity = presentation.identity
                            ready.successful_at = self._monotonic_clock()
                        ready.error = None
                        ready.retry_at = 0.0
                        ready.retry_delay = 1.0
                        ready.retry_attempts = 0
                        ready.recoverable_failure = False
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

    @staticmethod
    def _publish_backend_image(
        backend: DisplayBackend,
        destination: DisplayOutputConfiguration,
        image: Image.Image,
        *,
        prepared_metadata: dict[str, object] | None = None,
        transient: bool = False,
        publication_finalizer: (
            Callable[[DisplayOutputConfiguration, dict[str, object] | None], dict[str, object]] | None
        ) = None,
    ) -> None:
        if isinstance(backend, PublicationDisplayBackend):
            if publication_finalizer is None:
                raise DisplayBackendUpdateError(
                    "application publication metadata finalizer is unavailable for a metadata destination",
                    recoverable=False,
                )
            if transient:
                completed_metadata = publication_finalizer(destination, None)
                backend.publish_transient(destination, image, completed_metadata)
                return
            if prepared_metadata is None:
                raise DisplayBackendUpdateError(
                    f"scheduled publication for destination {destination.identifier!r} " "is missing prepared metadata"
                )
            completed_metadata = publication_finalizer(destination, prepared_metadata)
            backend.publish_scheduled(destination, image, completed_metadata)
            return
        backend.publish(destination, image)

    def _signal_all_unavailable(self) -> None:
        participating = [state for state in self._states.values() if not state.withdrawn]
        if self._all_unavailable_event is not None and participating and all(state.terminal for state in participating):
            self._all_unavailable_event.set()

    @staticmethod
    def _renew_recovery(states: Iterable[_DestinationState]) -> None:
        for state in states:
            if not state.recoverable_failure or state.withdrawn:
                continue
            state.terminal = False
            state.error = None
            state.retry_at = 0.0
            state.retry_delay = 1.0
            state.retry_attempts = 0


__all__ = [
    "DisplayPublicationCoordinator",
    "PublicationOperation",
    "PublicationResult",
    "PublicationStatus",
]

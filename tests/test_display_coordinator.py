from __future__ import annotations

import time
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest
from PIL import Image

from refrain import (
    DisplayBackendConfiguration,
    DisplayOutputConfiguration,
    ResolvedOutputSpecification,
)
from refrain.display import DisplayBackendInitializationError, DisplayBackendUpdateError
from refrain.display import coordinator as coordinator_module
from refrain.display.coordinator import DisplayPublicationCoordinator, PublicationStatus

_SPECIFICATION = ResolvedOutputSpecification("16:9", (1920, 1080))
_OUTPUT = DisplayOutputConfiguration("default", _SPECIFICATION)


def configuration(backend_type: str) -> DisplayBackendConfiguration:
    return DisplayBackendConfiguration(backend_type, outputs=(_OUTPUT,))


def publication(value: int) -> dict[ResolvedOutputSpecification, Image.Image]:
    return {_SPECIFICATION: image(value)}


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class SimulatedBackend:
    def __init__(self, backend_type: str, updates: dict[str, list[int]], *, gates=None) -> None:
        self.backend_type = backend_type
        self.updates = updates
        self.gates = gates or {}
        self.closed = False
        self.destinations: list[str] = []
        self.images: list[Image.Image] = []

    def update(self, image: Image.Image) -> None:
        value = image.getpixel((0, 0))[0]
        self.updates[self.backend_type].append(value)
        gate = self.gates.get(value)
        if gate is not None:
            entered, release = gate
            entered.set()
            assert release.wait(2)
            assert image.getpixel((0, 0))[0] == value

    def publish(self, destination: DisplayOutputConfiguration, image: Image.Image) -> None:
        self.destinations.append(destination.identifier)
        self.images.append(image)
        self.update(image)

    def update_output(self, _output_id: str, image: Image.Image) -> None:
        self.update(image)

    def close(self) -> None:
        self.closed = True


def image(value: int) -> Image.Image:
    return Image.new("RGB", (4, 4), (value, 0, 0))


@pytest.mark.parametrize("wait_method", ["wait_for_publication", "wait_for_any_publication"])
def test_withdrawal_wakes_publication_waiters(wait_method: str) -> None:
    entered, release, waiting, done = Event(), Event(), Event(), Event()
    results = []

    def factory(config):
        entered.set()
        assert release.wait(5)
        return SimulatedBackend(config.type, {"window": []})

    coordinator = DisplayPublicationCoordinator((configuration("window"),), factory)

    def wait():
        waiting.set()
        results.append(getattr(coordinator, wait_method)((1, 0)))
        done.set()

    waiter = Thread(target=wait)
    try:
        coordinator.publish((1, 0), publication(1))
        assert entered.wait(2)
        waiter.start()
        assert waiting.wait(2)
        assert coordinator.withdraw_destination("window")
        assert done.wait(2)
        assert results == [False]
    finally:
        release.set()
        waiter.join(2)
        coordinator.close()


def test_withdrawal_signals_when_remaining_destinations_are_terminal() -> None:
    all_unavailable, failed = Event(), Event()

    def factory(config):
        if config.type == "image-server":
            failed.set()
            raise DisplayBackendInitializationError("unavailable", recoverable=False)
        return SimulatedBackend(config.type, {"window": []})

    coordinator = DisplayPublicationCoordinator(
        (configuration("window"), configuration("image-server")), factory, all_unavailable_event=all_unavailable
    )
    try:
        coordinator.publish((1, 0), publication(1))
        assert failed.wait(2)
        assert wait_until(lambda: not coordinator.destination_statuses[1]["available"])
        assert not all_unavailable.is_set()
        assert coordinator.withdraw_destination("window")
        assert all_unavailable.is_set()
    finally:
        coordinator.close()


def test_backend_withdraws_all_its_destinations_atomically() -> None:
    all_unavailable = Event()
    callbacks = []
    outputs = (DisplayOutputConfiguration("one", _SPECIFICATION), DisplayOutputConfiguration("two", _SPECIFICATION))
    config = DisplayBackendConfiguration("image-server", outputs=outputs)

    class Backend(SimulatedBackend):
        def set_withdrawal_callback(self, callback):
            callbacks.append(callback)

    coordinator = DisplayPublicationCoordinator(
        (config,), lambda config: Backend(config.type, {"image-server": []}), all_unavailable_event=all_unavailable
    )
    try:
        coordinator.publish((1, 0), publication(1))
        assert coordinator.wait_for_publication((1, 0), timeout=2)
        with coordinator._condition:
            coordinator._states["image-server:two"].terminal = True
        callbacks[0]()
        assert all(status["withdrawn"] for status in coordinator.destination_statuses)
        assert not all_unavailable.is_set()
    finally:
        coordinator.close()


def test_slow_backend_does_not_block_another_and_obsolete_work_is_coalesced() -> None:
    configurations = (configuration("window"), configuration("image-server"))
    updates = {"window": [], "image-server": []}
    first_entered, release_first = Event(), Event()
    latest_entered, release_latest = Event(), Event()
    backends = {}

    def factory(configuration):
        gates = {1: (first_entered, release_first), 3: (latest_entered, release_latest)}
        backend = SimulatedBackend(configuration.type, updates, gates=gates if configuration.type == "window" else {})
        backends[configuration.type] = backend
        return backend

    coordinator = DisplayPublicationCoordinator(configurations, factory)
    try:
        coordinator.publish((7, 0), publication(1))
        assert first_entered.wait(1)
        assert wait_until(lambda: coordinator.acknowledgements["image-server:default"] == (7, 0))

        coordinator.publish((7, 1), publication(2))
        assert wait_until(lambda: updates["image-server"][-1:] == [2])
        coordinator.publish((7, 2), publication(3))
        assert wait_until(lambda: coordinator.acknowledgements["image-server:default"] == (7, 2))
        assert updates["window"] == [1]

        release_first.set()
        assert latest_entered.wait(1)
        assert coordinator.acknowledgements["window"] == (7, 0)
        release_latest.set()
        assert coordinator.wait_for_publication((7, 2), timeout=1)
        assert updates["window"] == [1, 3]
        assert coordinator.acknowledgements == {
            "window": (7, 2),
            "image-server:default": (7, 2),
        }
    finally:
        release_first.set()
        release_latest.set()
        coordinator.close()

    assert all(backend.closed for backend in backends.values())


def test_identical_desired_presentation_is_not_published_twice() -> None:
    window_configuration = (configuration("window"),)
    updates = {"window": []}
    backend = SimulatedBackend("window", updates)
    coordinator = DisplayPublicationCoordinator(window_configuration, lambda _configuration: backend)
    try:
        coordinator.publish((3, 1), publication(9))
        assert coordinator.wait_for_publication((3, 1), timeout=1)
        coordinator.publish((3, 1), publication(9))
        time.sleep(0.02)
        assert updates["window"] == [9]
    finally:
        coordinator.close()


def test_destinations_receive_images_matching_their_output_specification() -> None:
    wide = ResolvedOutputSpecification("16:9", (1920, 1080))
    portrait = ResolvedOutputSpecification("4:3", (1600, 1200))
    configurations = (
        DisplayBackendConfiguration("window", outputs=(DisplayOutputConfiguration("window", wide),)),
        DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("default", portrait),)),
    )
    updates = {"window": [], "image-server": []}
    backends = {}

    def factory(backend_configuration):
        backend = SimulatedBackend(backend_configuration.type, updates)
        backends[backend_configuration.type] = backend
        return backend

    coordinator = DisplayPublicationCoordinator(configurations, factory)
    images = {wide: image(21), portrait: image(42)}
    try:
        coordinator.publish((4, 2), images)
        assert coordinator.wait_for_publication((4, 2), timeout=1)
        assert updates == {"window": [21], "image-server": [42]}
    finally:
        coordinator.close()


@pytest.mark.parametrize("failure", ["initialization", "update"])
def test_terminal_backend_failure_does_not_stop_an_operational_destination(failure: str) -> None:
    configurations = (configuration("window"), configuration("image-server"))
    updates = {"image-server": []}
    healthy = SimulatedBackend("image-server", updates)
    closed = Event()

    def factory(configuration):
        if configuration.type == "window":
            if failure == "initialization":
                raise DisplayBackendInitializationError("no graphical session", recoverable=False)

            class DisabledBackend:
                def update(self, image):
                    raise DisplayBackendUpdateError("display disabled", recoverable=False)

                def publish(self, destination, image):
                    del destination
                    self.update(image)

                def close(self):
                    closed.set()

            return DisabledBackend()
        return healthy

    coordinator = DisplayPublicationCoordinator(configurations, factory)
    try:
        coordinator.publish((5, 0), publication(4))
        assert coordinator.wait_for_publication((5, 0), timeout=1)
        assert not coordinator.all_unavailable
        assert coordinator.acknowledgements == {"window": None, "image-server:default": (5, 0)}
        results = coordinator.publication_results((5, 0))
        window_error = "no graphical session" if failure == "initialization" else "display disabled"
        assert results["window"] == (False, window_error)
        assert results["image-server:default"] == (True, None)
    finally:
        coordinator.close()
    assert healthy.closed
    assert closed.is_set() is (failure == "update")


def test_recoverable_initialization_failure_is_retried() -> None:
    window_configuration = (configuration("window"),)
    attempts = []
    updates = {"window": []}
    backend = SimulatedBackend("window", updates)

    def factory(_configuration):
        attempts.append(1)
        if len(attempts) == 1:
            raise DisplayBackendInitializationError("temporarily unavailable")
        return backend

    coordinator = DisplayPublicationCoordinator(window_configuration, factory)
    try:
        coordinator.publish((9, 0), publication(7))
        assert coordinator.wait_for_publication((9, 0), timeout=3)
        assert len(attempts) == 2 and updates["window"] == [7]
    finally:
        coordinator.close()
    assert backend.closed


def test_recoverable_update_failure_retries_without_reinitializing() -> None:
    window_configuration = (configuration("window"),)
    attempts = []

    class RecoveringBackend(SimulatedBackend):
        def update(self, image):
            attempts.append(1)
            if len(attempts) == 1:
                raise DisplayBackendUpdateError("temporarily unavailable")
            super().update(image)

    updates = {"window": []}
    backend = RecoveringBackend("window", updates)
    coordinator = DisplayPublicationCoordinator(window_configuration, lambda _configuration: backend)
    try:
        coordinator.publish((8, 0), publication(6))
        assert coordinator.wait_for_publication((8, 0), timeout=3)
        assert len(attempts) == 2 and updates["window"] == [6]
    finally:
        coordinator.close()
    assert backend.closed


@pytest.mark.parametrize("operation", ["initialization", "update"])
def test_unexpected_backend_exception_is_terminal(operation: str) -> None:
    window_configuration = (configuration("window"),)
    attempts = []
    backend_closed = Event()

    class UnexpectedBackend:
        def update(self, image):
            attempts.append("update")
            raise RuntimeError("programming error")

        def publish(self, destination, image):
            del destination
            self.update(image)

        def close(self):
            backend_closed.set()

    def factory(_configuration):
        attempts.append("initialize")
        if operation == "initialization":
            raise RuntimeError("programming error")
        return UnexpectedBackend()

    coordinator = DisplayPublicationCoordinator(window_configuration, factory)
    coordinator.publish((10, 0), publication(5))
    try:
        assert wait_until(lambda: coordinator.all_unavailable)
        expected_attempts = ["initialize"] if operation == "initialization" else ["initialize", "update"]
        assert attempts == expected_attempts
    finally:
        coordinator.close()
    assert backend_closed.is_set() is (operation == "update")


def test_shutdown_wait_is_bounded_and_keeps_active_image_alive(monkeypatch, caplog) -> None:
    monkeypatch.setattr("refrain.display.coordinator._SHUTDOWN_TIMEOUT", 0.02)
    entered, release = Event(), Event()
    backend_closed = Event()
    retained_images = []

    class BlockingBackend:
        def publish(self, destination, image):
            del destination
            retained_images.append(image)
            entered.set()
            assert release.wait(2)
            assert image.getpixel((0, 0)) == (12, 0, 0)

        def close(self):
            backend_closed.set()

    backend = BlockingBackend()
    coordinator = DisplayPublicationCoordinator(
        (configuration("window"),),
        lambda _configuration: backend,
    )
    coordinator.publish((11, 0), publication(12))
    assert entered.wait(1)

    started = time.monotonic()
    with caplog.at_level("ERROR"):
        pending = coordinator.close()

    assert time.monotonic() - started < 0.5
    assert len(pending) == 1 and pending[0].is_alive()
    assert "did not stop within" in caplog.text
    assert not backend_closed.is_set()
    assert retained_images[0].getpixel((0, 0)) == (12, 0, 0)

    release.set()
    assert backend_closed.wait(1)


def test_drain_finishes_admitted_destinations_and_rejects_new_work() -> None:
    specification = ResolvedOutputSpecification("16:9", (8, 4))
    outputs = tuple(DisplayOutputConfiguration(name, specification) for name in ("one", "two"))
    entered, release, closed = Event(), Event(), Event()
    published = []

    class Backend:
        def publish(self, destination, image):
            if destination.identifier == "one":
                entered.set()
                assert release.wait(5)
            assert image.getpixel((0, 0)) == (7, 8, 9)
            assert not closed.is_set()
            published.append(destination.identifier)

        def close(self):
            closed.set()

    config = DisplayBackendConfiguration("image-server", outputs=outputs)
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend())
    image = Image.new("RGB", (8, 4), (7, 8, 9))
    specs = {f"image-server:{name}": specification for name in ("one", "two")}
    operation = coordinator.publish_transient("all", specs, {specification: image})
    try:
        assert entered.wait(5)
        scheduled = Image.new("RGB", (8, 4))
        coordinator.publish((1, 0), {specification: scheduled})
        coordinator.begin_draining()
        with pytest.raises(ValueError):
            scheduled.getpixel((0, 0))
        rejected = coordinator.publish_transient("all", specs, {specification: Image.new("RGB", (8, 4))})
        assert rejected.result.status is PublicationStatus.STOPPING
        refresh = coordinator.force_scheduled_publication((1, 0), {specification: Image.new("RGB", (8, 4))})
        assert refresh.result.status is PublicationStatus.STOPPING
        with pytest.raises(RuntimeError, match="stopping"):
            coordinator.publish((1, 1), {specification: Image.new("RGB", (8, 4))})
        assert not closed.is_set()
        release.set()
        assert operation.wait(5).status is PublicationStatus.SUCCEEDED
        assert published == ["one", "two"]
    finally:
        release.set()
        coordinator.close()
    assert closed.is_set()


def test_drain_finishes_other_destinations_after_active_recoverable_failure() -> None:
    specification = ResolvedOutputSpecification("16:9", (8, 4))
    outputs = tuple(DisplayOutputConfiguration(name, specification) for name in ("one", "two"))
    entered, release = Event(), Event()
    attempts = []

    class Backend:
        def publish(self, destination, image):
            attempts.append(destination.identifier)
            if destination.identifier == "one":
                entered.set()
                assert release.wait(5)
                raise DisplayBackendUpdateError("retry later")
            assert image.getpixel((0, 0)) == (0, 0, 0)

        def close(self):
            pass

    config = DisplayBackendConfiguration("image-server", outputs=outputs)
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend())
    specs = {f"image-server:{name}": specification for name in ("one", "two")}
    operation = coordinator.publish_transient("all", specs, {specification: Image.new("RGB", (8, 4))})
    try:
        assert entered.wait(5)
        coordinator.begin_draining()
        release.set()
        result = operation.wait(5)
        assert result.status is PublicationStatus.FAILED
        assert not coordinator.all_unavailable
        assert result.destinations == {
            "image-server:one": (False, "retry later"),
            "image-server:two": (True, None),
        }
        assert attempts == ["one", "two"]
    finally:
        release.set()
        coordinator.close()


@pytest.mark.parametrize("failure_point", ["initialization", "publication"])
def test_drain_stops_recoverable_one_shot_retries(failure_point) -> None:
    specification = ResolvedOutputSpecification("16:9", (8, 4))
    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("one", specification),))
    attempts = []

    class Backend:
        def publish(self, destination, image):
            attempts.append("publication")
            raise DisplayBackendUpdateError("retry later")

        def close(self):
            pass

    def factory(_):
        if failure_point == "initialization":
            attempts.append("initialization")
            raise DisplayBackendInitializationError("retry later")
        return Backend()

    coordinator = DisplayPublicationCoordinator((config,), factory)
    operation = coordinator.publish_transient(
        "image-server:one", {"image-server:one": specification}, {specification: Image.new("RGB", (8, 4))}
    )
    try:

        def waiting_for_retry():
            with coordinator._condition:
                state = coordinator._states["image-server:one"]
                return state.one_shot is not None and state.one_shot.retry_at[state.key] > 0

        assert wait_until(waiting_for_retry)
        coordinator.begin_draining()
        result = operation.wait(5)
        assert result.status is PublicationStatus.FAILED
        assert result.destinations["image-server:one"] == (False, "retry later")
        assert attempts == [failure_point]
    finally:
        coordinator.close()


def test_drain_stops_retries_when_factory_fails_after_shutdown() -> None:
    specification = ResolvedOutputSpecification("16:9", (8, 4))
    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("one", specification),))
    entered, release = Event(), Event()
    attempts = []

    def factory(_):
        attempts.append("initialization")
        entered.set()
        assert release.wait(5)
        raise DisplayBackendInitializationError("retry later")

    coordinator = DisplayPublicationCoordinator((config,), factory)
    operation = coordinator.publish_transient(
        "image-server:one", {"image-server:one": specification}, {specification: Image.new("RGB", (8, 4))}
    )
    try:
        assert entered.wait(5)
        coordinator.begin_draining()
        release.set()
        result = operation.wait(5)
        assert result.status is PublicationStatus.FAILED
        assert not coordinator.all_unavailable
        assert result.destinations["image-server:one"] == (False, "retry later")
        assert attempts == ["initialization"]
    finally:
        release.set()
        coordinator.close()


def test_drain_completes_withdrawn_one_shot_after_factory_failure() -> None:
    specification = ResolvedOutputSpecification("16:9", (8, 4))
    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("one", specification),))
    entered, release = Event(), Event()
    attempts = []

    def factory(_):
        attempts.append("initialization")
        entered.set()
        assert release.wait(5)
        raise DisplayBackendInitializationError("retry later")

    coordinator = DisplayPublicationCoordinator((config,), factory)
    operation = coordinator.publish_transient(
        "image-server:one", {"image-server:one": specification}, {specification: Image.new("RGB", (8, 4))}
    )
    try:
        assert entered.wait(5)
        assert coordinator.withdraw_destination("image-server:one")
        coordinator.begin_draining()
        release.set()
        result = operation.wait(5)
        assert result.status is PublicationStatus.FAILED
        assert result.destinations["image-server:one"] == (False, "retry later")
        assert attempts == ["initialization"]
    finally:
        release.set()
        coordinator.close()


def test_drain_bypasses_earlier_scheduled_factory_backoff(monkeypatch) -> None:
    specification = ResolvedOutputSpecification("16:9", (8, 4))
    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("one", specification),))
    attempts = []
    initial_time = time.monotonic()
    monkeypatch.setattr(coordinator_module, "time", SimpleNamespace(monotonic=lambda: initial_time))

    class Backend:
        def publish(self, destination, image):
            assert image.getpixel((0, 0)) == (0, 0, 0)

        def close(self):
            pass

    def factory(_):
        attempts.append("initialization")
        if len(attempts) == 1:
            raise DisplayBackendInitializationError("retry later")
        return Backend()

    coordinator = DisplayPublicationCoordinator((config,), factory)
    try:
        coordinator.publish((1, 0), {specification: Image.new("RGB", (8, 4))})
        assert wait_until(lambda: coordinator.destination_statuses[0]["available"] is False)
        coordinator.clear_desired()
        operation = coordinator.publish_transient(
            "image-server:one", {"image-server:one": specification}, {specification: Image.new("RGB", (8, 4))}
        )
        assert operation.result.status is PublicationStatus.ACCEPTED
        coordinator.begin_draining()
        assert operation.wait(2).status is PublicationStatus.SUCCEEDED
        assert attempts == ["initialization", "initialization"]
    finally:
        coordinator.close()


def test_drain_wakes_scheduled_publication_waiters() -> None:
    entered, release = Event(), Event()
    results = []

    class Backend:
        def publish(self, destination, image):
            entered.set()
            assert release.wait(5)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((configuration("window"),), lambda _: Backend())
    coordinator.publish((1, 0), publication(1))
    assert entered.wait(5)
    coordinator.publish((1, 1), publication(2))
    waiters = [
        Thread(target=lambda: results.append(coordinator.wait_for_publication((1, 1)))),
        Thread(target=lambda: results.append(coordinator.wait_for_any_publication((1, 1)))),
    ]
    try:
        for waiter in waiters:
            waiter.start()
        coordinator.begin_draining()
        for waiter in waiters:
            waiter.join(2)
            assert not waiter.is_alive()
        assert results == [False, False]
    finally:
        release.set()
        coordinator.close()


def test_shutdown_waits_for_successful_update_and_backend_cleanup(monkeypatch) -> None:
    update_entered, release_update = Event(), Event()
    join_started, close_entered, release_close, shutdown_finished = Event(), Event(), Event(), Event()
    active = Event()
    closed_while_active = []

    class Backend:
        def publish(self, destination, image):
            del destination
            active.set()
            update_entered.set()
            try:
                assert release_update.wait(10)
                assert image.getpixel((0, 0)) == (12, 0, 0)
            finally:
                active.clear()

        def close(self):
            closed_while_active.append(active.is_set())
            close_entered.set()
            assert release_close.wait(10)

    coordinator = DisplayPublicationCoordinator((configuration("window"),), lambda _configuration: Backend())
    worker = coordinator._threads[0]
    original_join = worker.join

    def join(timeout=None):
        join_started.set()
        original_join(timeout)

    monkeypatch.setattr(worker, "join", join)
    shutdown = Thread(target=lambda: (coordinator.close(), shutdown_finished.set()))
    try:
        coordinator.publish((11, 2), publication(12))
        assert update_entered.wait(10)
        shutdown.start()
        assert join_started.wait(10)
        assert not close_entered.is_set()
        assert coordinator.acknowledgements == {"window": None}
        assert not shutdown_finished.is_set()

        release_update.set()
        assert close_entered.wait(10)
        assert not shutdown_finished.is_set()
        release_close.set()
        shutdown.join(10)
        assert not shutdown.is_alive()
        assert shutdown_finished.is_set()
        assert coordinator.acknowledgements == {"window": (11, 2)}
        assert closed_while_active == [False]
    finally:
        release_update.set()
        release_close.set()
        if shutdown.ident is not None:
            shutdown.join(10)
        else:
            coordinator.close()


def test_canonical_destination_identifiers_are_unique_and_keep_output_mapping() -> None:
    portrait = ResolvedOutputSpecification("4:3", (1600, 1200))
    configurations = (
        DisplayBackendConfiguration("window", outputs=(DisplayOutputConfiguration("window", _SPECIFICATION),)),
        DisplayBackendConfiguration(
            "waveshare-13in3-e",
            outputs=(DisplayOutputConfiguration("waveshare-13in3-e", portrait),),
        ),
        DisplayBackendConfiguration(
            "image-server",
            outputs=(
                DisplayOutputConfiguration("kitchen", _SPECIFICATION),
                DisplayOutputConfiguration("hallway", portrait),
            ),
        ),
    )
    coordinator = DisplayPublicationCoordinator(configurations, lambda _configuration: None)
    try:
        assert coordinator.destination_identifiers == (
            "window",
            "waveshare-13in3-e",
            "image-server:kitchen",
            "image-server:hallway",
        )
        assert len(set(coordinator.destination_identifiers)) == 4
        assert coordinator._states["window"].destination.output_specification == _SPECIFICATION
        assert coordinator._states["waveshare-13in3-e"].destination.output_specification == portrait
        assert coordinator._states["image-server:kitchen"].destination.identifier == "kitchen"
        assert coordinator._states["image-server:hallway"].destination.output_specification == portrait
        assert coordinator._states["image-server:kitchen"].backend_configuration is configurations[2]
        assert coordinator._states["image-server:hallway"].backend_configuration is configurations[2]
    finally:
        coordinator.close()


def test_destinations_on_one_backend_are_serialized_while_other_backend_progresses() -> None:
    image_server_configuration = DisplayBackendConfiguration(
        "image-server",
        outputs=(
            DisplayOutputConfiguration("kitchen", _SPECIFICATION),
            DisplayOutputConfiguration("hallway", _SPECIFICATION),
        ),
    )
    configurations = (image_server_configuration, configuration("window"))
    entered, release = Event(), Event()
    window_published = Event()
    active: dict[str, int] = {}
    maximum_active: dict[str, int] = {}
    lock = Lock()
    construction_counts: dict[str, int] = {}
    destinations: list[str] = []

    class Backend:
        def __init__(self, backend_type: str) -> None:
            self.backend_type = backend_type

        def publish(self, destination, image):
            with lock:
                active[self.backend_type] = active.get(self.backend_type, 0) + 1
                maximum_active[self.backend_type] = max(
                    maximum_active.get(self.backend_type, 0),
                    active[self.backend_type],
                )
            try:
                destinations.append(f"{self.backend_type}:{destination.identifier}")
                if self.backend_type == "image-server" and destination.identifier == "kitchen":
                    entered.set()
                    assert release.wait(2)
                if self.backend_type == "window":
                    window_published.set()
            finally:
                with lock:
                    active[self.backend_type] -= 1

        def close(self):
            pass

    def factory(backend_configuration):
        construction_counts[backend_configuration.type] = construction_counts.get(backend_configuration.type, 0) + 1
        return Backend(backend_configuration.type)

    coordinator = DisplayPublicationCoordinator(configurations, factory)
    try:
        coordinator.publish((12, 0), publication(15))
        assert entered.wait(1)
        assert window_published.wait(1)
        assert "image-server:hallway" not in destinations
        assert maximum_active["image-server"] == 1
        release.set()
        assert coordinator.wait_for_publication((12, 0), timeout=1)
        assert wait_until(lambda: coordinator.acknowledgements["image-server:hallway"] == (12, 0))
        assert destinations.count("image-server:kitchen") == 1
        assert destinations.count("image-server:hallway") == 1
        assert construction_counts == {"image-server": 1, "window": 1}
        assert len(coordinator._threads) == 2
    finally:
        release.set()
        coordinator.close()


def test_same_spec_destinations_have_independent_acknowledgements_and_route() -> None:
    server_configuration = DisplayBackendConfiguration(
        "image-server",
        outputs=(
            DisplayOutputConfiguration("kitchen", _SPECIFICATION),
            DisplayOutputConfiguration("hallway", _SPECIFICATION),
        ),
    )
    updates = {"image-server": []}
    backend = SimulatedBackend("image-server", updates)
    coordinator = DisplayPublicationCoordinator((server_configuration,), lambda _configuration: backend)
    try:
        images = publication(28)
        shared_image = images[_SPECIFICATION]
        coordinator.publish((13, 2), images)
        assert coordinator.wait_for_publication((13, 2), timeout=1)
        assert wait_until(lambda: coordinator.acknowledgements["image-server:hallway"] == (13, 2))
        assert coordinator.acknowledgements == {
            "image-server:kitchen": (13, 2),
            "image-server:hallway": (13, 2),
        }
        assert backend.destinations == ["kitchen", "hallway"]
        assert backend.images == [shared_image, shared_image]
        assert backend.images[0] is backend.images[1]
        with pytest.raises(ValueError):
            shared_image.getpixel((0, 0))
    finally:
        coordinator.close()


def test_failure_of_one_named_destination_does_not_fail_its_sibling() -> None:
    server_configuration = DisplayBackendConfiguration(
        "image-server",
        outputs=(
            DisplayOutputConfiguration("kitchen", _SPECIFICATION),
            DisplayOutputConfiguration("hallway", _SPECIFICATION),
        ),
    )
    close_called = Event()
    published: list[str] = []

    class PartiallyAvailableBackend:
        def publish(self, destination, _image):
            if destination.identifier == "kitchen":
                raise DisplayBackendUpdateError("kitchen unavailable", recoverable=False)
            published.append(destination.identifier)

        def close(self):
            close_called.set()

    coordinator = DisplayPublicationCoordinator(
        (server_configuration,),
        lambda _configuration: PartiallyAvailableBackend(),
    )
    try:
        coordinator.publish((15, 0), publication(41))
        assert coordinator.wait_for_publication((15, 0), timeout=1)
        assert coordinator.acknowledgements == {
            "image-server:kitchen": None,
            "image-server:hallway": (15, 0),
        }
        assert coordinator.publication_results((15, 0)) == {
            "image-server:kitchen": (False, "kitchen unavailable"),
            "image-server:hallway": (True, None),
        }
        assert published == ["hallway"]
        assert not coordinator.all_unavailable
    finally:
        coordinator.close()
    assert close_called.is_set()


def test_images_are_closed_once_when_all_destinations_are_terminal(monkeypatch) -> None:
    portrait = ResolvedOutputSpecification("4:3", (1600, 1200))
    configurations = (
        DisplayBackendConfiguration("window", outputs=(DisplayOutputConfiguration("window", _SPECIFICATION),)),
        DisplayBackendConfiguration(
            "waveshare-13in3-e",
            outputs=(DisplayOutputConfiguration("waveshare-13in3-e", portrait),),
        ),
    )

    class UnavailableBackend:
        def publish(self, _destination, _image):
            raise DisplayBackendUpdateError("destination unavailable", recoverable=False)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator(configurations, lambda _configuration: UnavailableBackend())
    images = {
        _SPECIFICATION: image(51),
        portrait: image(52),
    }
    image_ids = {id(value) for value in images.values()}
    close_counts = {image_id: 0 for image_id in image_ids}
    original_close = Image.Image.close

    def close_and_count(closed_image):
        if id(closed_image) in close_counts:
            close_counts[id(closed_image)] += 1
        original_close(closed_image)

    monkeypatch.setattr(Image.Image, "close", close_and_count)
    try:
        coordinator.publish((16, 0), {_SPECIFICATION: image(53), portrait: image(54)})
        assert wait_until(lambda: coordinator.all_unavailable)

        coordinator.publish((16, 1), images)

        assert close_counts == {image_id: 1 for image_id in image_ids}
    finally:
        coordinator.close()


def test_desired_work_coalesces_during_backend_construction() -> None:
    initialization_entered, release_initialization = Event(), Event()
    first, second, latest = image(31), image(32), image(33)
    backend = SimulatedBackend("window", {"window": []})

    def factory(_configuration):
        initialization_entered.set()
        assert release_initialization.wait(2)
        return backend

    coordinator = DisplayPublicationCoordinator((configuration("window"),), factory)
    try:
        coordinator.publish((14, 0), {_SPECIFICATION: first})
        assert initialization_entered.wait(1)
        coordinator.publish((14, 1), {_SPECIFICATION: second})
        coordinator.publish((14, 2), {_SPECIFICATION: latest})
        with pytest.raises(ValueError):
            first.getpixel((0, 0))
        with pytest.raises(ValueError):
            second.getpixel((0, 0))

        release_initialization.set()
        assert coordinator.wait_for_publication((14, 2), timeout=1)
        assert wait_until(lambda: coordinator.acknowledgements["window"] == (14, 2))
        assert backend.updates["window"] == [33]
        with pytest.raises(ValueError):
            latest.getpixel((0, 0))
    finally:
        release_initialization.set()
        coordinator.close()

from __future__ import annotations

import time
from threading import Event, Lock, Thread

import pytest
from PIL import Image

from refrain import (
    DisplayBackendConfiguration,
    DisplayOutputConfiguration,
    ResolvedOutputSpecification,
)
from refrain.display import DisplayBackendInitializationError, DisplayBackendUpdateError
from refrain.display.coordinator import DisplayPublicationCoordinator

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

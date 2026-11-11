from __future__ import annotations

import time
from threading import Event, Thread

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

    def update(self, image: Image.Image) -> None:
        value = image.getpixel((0, 0))[0]
        self.updates[self.backend_type].append(value)
        gate = self.gates.get(value)
        if gate is not None:
            entered, release = gate
            entered.set()
            assert release.wait(2)
            assert image.getpixel((0, 0))[0] == value

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
        assert coordinator.acknowledgements["window:default"] == (7, 0)
        release_latest.set()
        assert coordinator.wait_for_publication((7, 2), timeout=1)
        assert updates["window"] == [1, 3]
        assert coordinator.acknowledgements == {
            "window:default": (7, 2),
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

                def close(self):
                    closed.set()

            return DisabledBackend()
        return healthy

    coordinator = DisplayPublicationCoordinator(configurations, factory)
    try:
        coordinator.publish((5, 0), publication(4))
        assert coordinator.wait_for_publication((5, 0), timeout=1)
        assert not coordinator.all_unavailable
        assert coordinator.acknowledgements == {"window:default": None, "image-server:default": (5, 0)}
        results = coordinator.publication_results((5, 0))
        window_error = "no graphical session" if failure == "initialization" else "display disabled"
        assert results["window:default"] == (False, window_error)
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
        def update(self, image):
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
        def update(self, image):
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
        assert coordinator.acknowledgements == {"window:default": None}
        assert not shutdown_finished.is_set()

        release_update.set()
        assert close_entered.wait(10)
        assert not shutdown_finished.is_set()
        release_close.set()
        shutdown.join(10)
        assert not shutdown.is_alive()
        assert shutdown_finished.is_set()
        assert coordinator.acknowledgements == {"window:default": (11, 2)}
        assert closed_while_active == [False]
    finally:
        release_update.set()
        release_close.set()
        if shutdown.ident is not None:
            shutdown.join(10)
        else:
            coordinator.close()

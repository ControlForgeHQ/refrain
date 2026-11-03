from __future__ import annotations

import time
from threading import Event

import pytest
from PIL import Image

from refrain import DisplayBackendConfiguration
from refrain.display import DisplayBackendInitializationError, DisplayBackendUpdateError
from refrain.display.coordinator import DisplayPublicationCoordinator


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

    def close(self) -> None:
        self.closed = True


def image(value: int) -> Image.Image:
    return Image.new("RGB", (4, 4), (value, 0, 0))


def test_slow_backend_does_not_block_another_and_obsolete_work_is_coalesced() -> None:
    configurations = (DisplayBackendConfiguration("window"), DisplayBackendConfiguration("image-server"))
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
        coordinator.publish((7, 0), image(1))
        assert first_entered.wait(1)
        assert wait_until(lambda: coordinator.acknowledgements["image-server"] == (7, 0))

        coordinator.publish((7, 1), image(2))
        assert wait_until(lambda: updates["image-server"][-1:] == [2])
        coordinator.publish((7, 2), image(3))
        assert wait_until(lambda: coordinator.acknowledgements["image-server"] == (7, 2))
        assert updates["window"] == [1]

        release_first.set()
        assert latest_entered.wait(1)
        assert coordinator.acknowledgements["window"] == (7, 0)
        release_latest.set()
        assert coordinator.wait_for_publication((7, 2), timeout=1)
        assert updates["window"] == [1, 3]
        assert coordinator.acknowledgements == {"window": (7, 2), "image-server": (7, 2)}
    finally:
        release_first.set()
        release_latest.set()
        coordinator.close()

    assert all(backend.closed for backend in backends.values())


def test_identical_desired_presentation_is_not_published_twice() -> None:
    configuration = (DisplayBackendConfiguration("window"),)
    updates = {"window": []}
    backend = SimulatedBackend("window", updates)
    coordinator = DisplayPublicationCoordinator(configuration, lambda _configuration: backend)
    try:
        coordinator.publish((3, 1), image(9))
        assert coordinator.wait_for_publication((3, 1), timeout=1)
        coordinator.publish((3, 1), image(9))
        time.sleep(0.02)
        assert updates["window"] == [9]
    finally:
        coordinator.close()


@pytest.mark.parametrize("failure", ["initialization", "update"])
def test_terminal_backend_failure_does_not_stop_an_operational_destination(failure: str) -> None:
    configurations = (DisplayBackendConfiguration("window"), DisplayBackendConfiguration("image-server"))
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
        coordinator.publish((5, 0), image(4))
        assert coordinator.wait_for_publication((5, 0), timeout=1)
        assert not coordinator.all_unavailable
        assert coordinator.acknowledgements == {"window": None, "image-server": (5, 0)}
    finally:
        coordinator.close()
    assert healthy.closed
    assert closed.is_set() is (failure == "update")


def test_recoverable_initialization_failure_is_retried() -> None:
    configuration = (DisplayBackendConfiguration("window"),)
    attempts = []
    updates = {"window": []}
    backend = SimulatedBackend("window", updates)

    def factory(_configuration):
        attempts.append(1)
        if len(attempts) == 1:
            raise DisplayBackendInitializationError("temporarily unavailable")
        return backend

    coordinator = DisplayPublicationCoordinator(configuration, factory)
    try:
        coordinator.publish((9, 0), image(7))
        assert coordinator.wait_for_publication((9, 0), timeout=3)
        assert len(attempts) == 2 and updates["window"] == [7]
    finally:
        coordinator.close()
    assert backend.closed


def test_recoverable_update_failure_retries_without_reinitializing() -> None:
    configuration = (DisplayBackendConfiguration("window"),)
    attempts = []

    class RecoveringBackend(SimulatedBackend):
        def update(self, image):
            attempts.append(1)
            if len(attempts) == 1:
                raise DisplayBackendUpdateError("temporarily unavailable")
            super().update(image)

    updates = {"window": []}
    backend = RecoveringBackend("window", updates)
    coordinator = DisplayPublicationCoordinator(configuration, lambda _configuration: backend)
    try:
        coordinator.publish((8, 0), image(6))
        assert coordinator.wait_for_publication((8, 0), timeout=3)
        assert len(attempts) == 2 and updates["window"] == [6]
    finally:
        coordinator.close()
    assert backend.closed


@pytest.mark.parametrize("operation", ["initialization", "update"])
def test_unexpected_backend_exception_is_terminal(operation: str) -> None:
    configuration = (DisplayBackendConfiguration("window"),)
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

    coordinator = DisplayPublicationCoordinator(configuration, factory)
    coordinator.publish((10, 0), image(5))
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
        (DisplayBackendConfiguration("window"),),
        lambda _configuration: backend,
    )
    coordinator.publish((11, 0), image(12))
    assert entered.wait(1)

    started = time.monotonic()
    with caplog.at_level("ERROR"):
        coordinator.close()

    assert time.monotonic() - started < 0.5
    assert "did not stop within" in caplog.text
    assert not backend_closed.is_set()
    assert retained_images[0].getpixel((0, 0)) == (12, 0, 0)

    release.set()
    assert backend_closed.wait(1)

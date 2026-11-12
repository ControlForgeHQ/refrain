from __future__ import annotations

import time
from threading import Event, Lock

import pytest
from PIL import Image

from refrain import DisplayBackendConfiguration, DisplayOutputConfiguration, ResolvedOutputSpecification
from refrain.display import DisplayBackendInitializationError, DisplayBackendUpdateError
from refrain.display.coordinator import DisplayPublicationCoordinator, PublicationStatus

_WIDE = ResolvedOutputSpecification("16:9", (16, 9))
_PORTRAIT = ResolvedOutputSpecification("4:3", (16, 12))


def _configuration(
    backend_type: str,
    outputs: tuple[tuple[str, ResolvedOutputSpecification], ...] | None = None,
) -> DisplayBackendConfiguration:
    outputs = outputs or ((backend_type, _WIDE),)
    return DisplayBackendConfiguration(
        backend_type,
        outputs=tuple(DisplayOutputConfiguration(identifier, specification) for identifier, specification in outputs),
    )


def _images(*specifications: ResolvedOutputSpecification, value: int = 2) -> dict:
    return {
        specification: Image.new("RGB", specification.requested_output_size, (value, 0, 0))
        for specification in set(specifications)
    }


def _track_image_closes(monkeypatch, images: dict) -> dict[int, int]:
    close_counts = {id(image): 0 for image in images.values()}
    original_close = Image.Image.close

    def close(image):
        if id(image) in close_counts:
            close_counts[id(image)] += 1
        original_close(image)

    monkeypatch.setattr(Image.Image, "close", close)
    return close_counts


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_backend_withdrawal_discards_pending_and_skips_future_publications() -> None:
    entered, release = Event(), Event()
    publications: dict[str, list[int]] = {"window": [], "image-server": []}
    backends = {}

    class Backend:
        def __init__(self, backend_type):
            self.backend_type = backend_type
            self.callback = None

        def set_withdrawal_callback(self, callback):
            self.callback = callback

        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications[self.backend_type].append(value)
            if self.backend_type == "window" and value == 1:
                entered.set()
                assert release.wait(5)

        def close(self):
            pass

    def factory(config):
        backend = Backend(config.type)
        backends[config.type] = backend
        return backend

    coordinator = DisplayPublicationCoordinator((_configuration("window"), _configuration("image-server")), factory)
    try:
        coordinator.publish((1, 0), _images(_WIDE, value=1))
        assert entered.wait(2)
        assert _wait_until(lambda: coordinator.acknowledgements["image-server:image-server"] == (1, 0))
        coordinator.publish((1, 1), _images(_WIDE, value=2))
        assert _wait_until(lambda: coordinator.acknowledgements["image-server:image-server"] == (1, 1))
        backends["window"].callback()
        assert coordinator._states["window"].pending is None
        assert coordinator.destination_statuses[0]["withdrawn"] is True
        release.set()
        assert _wait_until(lambda: coordinator._states["window"].active_identity is None)
        coordinator.publish((1, 2), _images(_WIDE, value=3))
        assert coordinator.wait_for_publication((1, 2), timeout=2)
        refresh = coordinator.force_scheduled_publication((1, 2), _images(_WIDE, value=4))
        assert refresh.wait(2).status is PublicationStatus.SUCCEEDED
        assert set(refresh.result.destinations) == {"image-server:image-server"}
        transient = coordinator.publish_transient("all", {"image-server:image-server": _WIDE}, _images(_WIDE, value=5))
        assert transient.wait(2).status is PublicationStatus.SUCCEEDED
        assert set(transient.result.destinations) == {"image-server:image-server"}
        rejected = coordinator.publish_transient("window", {"window": _WIDE}, _images(_WIDE))
        assert rejected.result.status is PublicationStatus.WITHDRAWN
        assert publications == {"window": [1], "image-server": [1, 2, 3, 4, 5]}
    finally:
        release.set()
        coordinator.close()


@pytest.mark.parametrize("recoverable", [False, True])
def test_withdrawal_during_scheduled_failure_preserves_availability(monkeypatch, recoverable: bool) -> None:
    entered, release = Event(), Event()
    backends = {}
    publications = []

    class Backend:
        def __init__(self, backend_type):
            self.backend_type = backend_type
            self.callback = None

        def set_withdrawal_callback(self, callback):
            self.callback = callback

        def publish(self, _destination, image):
            publications.append((self.backend_type, image.getpixel((0, 0))[0]))
            if self.backend_type == "window":
                entered.set()
                assert release.wait(5)
                raise DisplayBackendUpdateError("window closed during publication", recoverable=recoverable)

        def close(self):
            pass

    def factory(config):
        backend = Backend(config.type)
        backends[config.type] = backend
        return backend

    coordinator = DisplayPublicationCoordinator((_configuration("window"), _configuration("image-server")), factory)
    images = _images(_WIDE, value=1)
    closes = _track_image_closes(monkeypatch, images)
    try:
        coordinator.publish((1, 0), images)
        assert entered.wait(2)
        assert _wait_until(lambda: coordinator.acknowledgements["image-server:image-server"] == (1, 0))
        coordinator.publish((1, 1), _images(_WIDE, value=2))
        assert _wait_until(lambda: coordinator.acknowledgements["image-server:image-server"] == (1, 1))
        backends["window"].callback()
        release.set()
        with coordinator._condition:
            assert coordinator._condition.wait_for(lambda: coordinator._states["window"].active_identity is None, 2)
        status = coordinator.destination_statuses[0]
        assert (status["participating"], status["withdrawn"], status["available"]) == (False, True, True)
        assert closes[id(images[_WIDE])] == 1
        coordinator.publish((1, 2), _images(_WIDE, value=3))
        assert coordinator.wait_for_publication((1, 2), timeout=2)
        assert [value for backend, value in publications if backend == "window"] == [1]
        assert [value for backend, value in publications if backend == "image-server"] == [1, 2, 3]
    finally:
        release.set()
        coordinator.close()


@pytest.mark.parametrize("forced", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_backend_withdrawal_does_not_cancel_admitted_one_shot(forced: bool, fail: bool) -> None:
    entered, release = Event(), Event()
    backends = {}
    publications: list[str] = []

    class Backend:
        def __init__(self, backend_type):
            self.backend_type = backend_type
            self.callback = None

        def set_withdrawal_callback(self, callback):
            self.callback = callback

        def publish(self, _destination, image):
            if image.getpixel((0, 0))[0] == 2:
                publications.append(self.backend_type)
                if self.backend_type == "window":
                    entered.set()
                    assert release.wait(5)
                    if fail:
                        raise DisplayBackendUpdateError("window closed during publication", recoverable=False)

        def close(self):
            pass

    def factory(config):
        backend = Backend(config.type)
        backends[config.type] = backend
        return backend

    coordinator = DisplayPublicationCoordinator((_configuration("window"), _configuration("image-server")), factory)
    try:
        coordinator.publish((1, 0), _images(_WIDE, value=1))
        assert coordinator.wait_for_publication((1, 0), timeout=2)
        if forced:
            operation = coordinator.force_scheduled_publication((1, 0), _images(_WIDE))
        else:
            operation = coordinator.publish_transient(
                "all", {"window": _WIDE, "image-server:image-server": _WIDE}, _images(_WIDE)
            )
        assert entered.wait(2)
        backends["window"].callback()
        assert coordinator.destination_statuses[0]["withdrawn"] is True
        assert set(operation.result.destinations) == {"window", "image-server:image-server"}
        release.set()
        assert operation.wait(2).status is (PublicationStatus.FAILED if fail else PublicationStatus.SUCCEEDED)
        assert operation.result.destinations["window"][0] is not fail
        if fail:
            assert operation.result.destinations["window"][1] == "window closed during publication"
        status = coordinator.destination_statuses[0]
        assert (status["participating"], status["withdrawn"], status["available"]) == (False, True, True)
        assert operation.result.destinations["image-server:image-server"][0] is True
        assert sorted(publications) == ["image-server", "window"]
    finally:
        release.set()
        coordinator.close()


def test_transient_publication_preserves_scheduled_acknowledgement_and_pixels_until_new_identity() -> None:
    transient_entered, release_transient = Event(), Event()
    publications: list[int] = []

    class Backend:
        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications.append(value)
            if value == 2:
                transient_entered.set()
                assert release_transient.wait(2)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend())
    try:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert coordinator.wait_for_publication((1, 0), timeout=1)
        acknowledged = coordinator.acknowledgements
        transient = coordinator.publish_transient(
            "window",
            {"window": _WIDE},
            _images(_WIDE),
        )
        assert transient_entered.wait(1)
        assert transient.result.status is PublicationStatus.ACCEPTED
        assert coordinator.acknowledgements == acknowledged
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (9, 0, 0))})
        release_transient.set()
        assert transient.wait(1).status is PublicationStatus.SUCCEEDED
        assert publications == [1, 2]
        assert coordinator.acknowledgements == acknowledged
    finally:
        release_transient.set()
        coordinator.close()


def test_transient_admission_is_atomic_when_one_selected_destination_is_busy() -> None:
    window_entered, release_window = Event(), Event()
    publications: list[tuple[str, int]] = []

    class Backend:
        def __init__(self, backend_type: str):
            self.backend_type = backend_type

        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications.append((self.backend_type, value))
            if self.backend_type == "window" and value == 1:
                window_entered.set()
                assert release_window.wait(2)

        def close(self):
            pass

    configurations = (
        _configuration("window"),
        _configuration("waveshare-13in3-e", (("waveshare-13in3-e", _PORTRAIT),)),
    )
    coordinator = DisplayPublicationCoordinator(configurations, lambda config: Backend(config.type))
    try:
        coordinator.publish(
            (1, 0),
            {
                _WIDE: Image.new("RGB", (4, 4), (1, 0, 0)),
                _PORTRAIT: Image.new("RGB", (4, 4), (1, 0, 0)),
            },
        )
        assert window_entered.wait(1)
        assert _wait_until(lambda: coordinator.acknowledgements["waveshare-13in3-e"] == (1, 0))
        request = coordinator.publish_transient(
            "all",
            {"window": _WIDE, "waveshare-13in3-e": _PORTRAIT},
            _images(_WIDE, _PORTRAIT),
        )
        assert request.result.status is PublicationStatus.BUSY
        release_window.set()
        assert coordinator.wait_for_publication((1, 0), timeout=1)
        assert sorted(publications) == [("waveshare-13in3-e", 1), ("window", 1)]
    finally:
        release_window.set()
        coordinator.close()


@pytest.mark.parametrize(
    ("target", "specifications", "image_specification", "capabilities", "withdraw", "expected"),
    [
        ("not-configured", {}, _WIDE, {}, False, PublicationStatus.DESTINATION_NOT_FOUND),
        ("window", {"window": _PORTRAIT}, _WIDE, {}, False, PublicationStatus.INVALID),
        ("window", {"window": _WIDE}, _WIDE, {"window": False}, False, PublicationStatus.UNSUPPORTED),
        ("window", {"window": _WIDE}, _WIDE, {}, True, PublicationStatus.WITHDRAWN),
    ],
)
def test_transient_rejections_do_not_access_backends(
    target,
    specifications,
    image_specification,
    capabilities,
    withdraw,
    expected,
) -> None:
    accessed: list[bool] = []

    class Backend:
        def publish(self, _destination, _image):
            accessed.append(True)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator(
        (_configuration("window"),),
        lambda _config: Backend(),
        transient_capabilities=capabilities,
    )
    try:
        if withdraw:
            assert coordinator.withdraw_destination("window")
        request = coordinator.publish_transient(target, specifications, _images(image_specification))
        assert request.result.status is expected
        assert accessed == []
    finally:
        coordinator.close()


def test_transient_validation_rejects_missing_and_wrong_sized_variants() -> None:
    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: None)
    try:
        missing = coordinator.publish_transient("window", {"window": _WIDE}, {})
        wrong_size = coordinator.publish_transient(
            "window",
            {"window": _WIDE},
            {_WIDE: Image.new("RGB", (15, 9))},
        )
        assert missing.result.status is PublicationStatus.INVALID
        assert wrong_size.result.status is PublicationStatus.INVALID
    finally:
        coordinator.close()


def test_all_skips_withdrawn_but_does_not_skip_failed_destinations() -> None:
    server_failed = Event()
    publications: list[str] = []

    class Backend:
        def __init__(self, backend_type: str):
            self.backend_type = backend_type

        def publish(self, destination, image):
            publications.append(self.backend_type)
            if self.backend_type == "window" and image.getpixel((0, 0))[0] == 3:
                server_failed.set()
                raise DisplayBackendUpdateError("window unavailable", recoverable=False)

        def close(self):
            pass

    configurations = (
        _configuration("window"),
        _configuration("waveshare-13in3-e", (("waveshare-13in3-e", _PORTRAIT),)),
    )
    coordinator = DisplayPublicationCoordinator(configurations, lambda config: Backend(config.type), retry=False)
    try:
        assert coordinator.withdraw_destination("waveshare-13in3-e")
        status_by_id = {entry["identifier"]: entry for entry in coordinator.destination_statuses}
        assert status_by_id["waveshare-13in3-e"]["withdrawn"] is True
        assert status_by_id["waveshare-13in3-e"]["available"] is True
        withdrawn_all = coordinator.publish_transient(
            "all",
            {"window": _WIDE},
            _images(_WIDE),
        )
        assert withdrawn_all.wait(1).status is PublicationStatus.SUCCEEDED
        assert withdrawn_all.result.destinations.keys() == {"window"}
        explicitly_withdrawn = coordinator.publish_transient(
            "waveshare-13in3-e",
            {"waveshare-13in3-e": _WIDE},
            _images(_WIDE),
        )
        assert explicitly_withdrawn.result.status is PublicationStatus.WITHDRAWN
        assert publications == ["window"]
    finally:
        coordinator.close()

    failed = DisplayPublicationCoordinator(configurations, lambda config: Backend(config.type), retry=False)
    try:
        request = failed.publish_transient(
            "all",
            {"window": _WIDE, "waveshare-13in3-e": _PORTRAIT},
            _images(_WIDE, _PORTRAIT, value=3),
        )
        result = request.wait(1)
        assert server_failed.wait(1)
        assert result.status is PublicationStatus.FAILED
        assert set(result.destinations) == {"window", "waveshare-13in3-e"}
        assert result.destinations["window"] == (False, "window unavailable")
        assert result.destinations["waveshare-13in3-e"] == (True, None)
        status_by_id = {entry["identifier"]: entry for entry in failed.destination_statuses}
        assert status_by_id["window"]["withdrawn"] is False
        assert status_by_id["window"]["available"] is False
    finally:
        failed.close()


def test_transient_blocks_scheduled_work_until_completion_and_coalesces_latest() -> None:
    transient_entered, release_transient = Event(), Event()
    publications: list[int] = []

    class Backend:
        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications.append(value)
            if value == 2:
                transient_entered.set()
                assert release_transient.wait(2)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend())
    try:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert coordinator.wait_for_publication((1, 0), timeout=1)
        transient = coordinator.publish_transient("window", {"window": _WIDE}, _images(_WIDE))
        assert transient_entered.wait(1)
        coordinator.publish((2, 0), {_WIDE: Image.new("RGB", (4, 4), (3, 0, 0))})
        coordinator.publish((3, 0), {_WIDE: Image.new("RGB", (4, 4), (4, 0, 0))})
        competing_transient = coordinator.publish_transient("window", {"window": _WIDE}, _images(_WIDE))
        competing_forced = coordinator.force_scheduled_publication((3, 0), _images(_WIDE))
        assert competing_transient.result.status is PublicationStatus.BUSY
        assert competing_forced.result.status is PublicationStatus.BUSY
        assert publications == [1, 2]
        release_transient.set()
        assert transient.wait(1).status is PublicationStatus.SUCCEEDED
        assert _wait_until(lambda: coordinator.acknowledgements["window"] == (3, 0))
        assert publications == [1, 2, 4]
    finally:
        release_transient.set()
        coordinator.close()


def test_shared_backend_destinations_are_serialized_while_unselected_backend_progresses() -> None:
    entered_window, release_window = Event(), Event()
    window_active = Event()
    active_server = 0
    max_active_server = 0
    lock = Lock()
    server_destinations: list[str] = []
    seen_images: list[Image.Image] = []

    class Backend:
        def __init__(self, backend_type: str):
            self.backend_type = backend_type

        def publish(self, destination, image):
            nonlocal active_server, max_active_server
            seen_images.append(image)
            assert image.getpixel((0, 0))[0] in (1, 2)
            if self.backend_type == "window":
                entered_window.set()
                window_active.set()
                assert release_window.wait(2)
                return
            with lock:
                active_server += 1
                max_active_server = max(max_active_server, active_server)
                server_destinations.append(destination.identifier)
            time.sleep(0.01)
            with lock:
                active_server -= 1

        def close(self):
            pass

    server = _configuration(
        "image-server",
        (("kitchen", _WIDE), ("hallway", _WIDE)),
    )
    coordinator = DisplayPublicationCoordinator((server, _configuration("window")), lambda config: Backend(config.type))
    try:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert entered_window.wait(1)
        assert _wait_until(lambda: coordinator.acknowledgements["image-server:hallway"] == (1, 0))
        request = coordinator.publish_transient(
            ("image-server:kitchen", "image-server:hallway"),
            {"image-server:kitchen": _WIDE, "image-server:hallway": _WIDE},
            _images(_WIDE),
        )
        assert request.wait(1).status is PublicationStatus.SUCCEEDED
        assert window_active.is_set()
        assert max_active_server == 1
        assert server_destinations == ["kitchen", "hallway", "kitchen", "hallway"]
        with pytest.raises(ValueError):
            seen_images[-1].getpixel((0, 0))
    finally:
        release_window.set()
        coordinator.close()


def test_forced_publication_repeats_current_identity_and_skips_withdrawn_destinations() -> None:
    publications: list[str] = []
    forced_images: list[Image.Image] = []

    class Backend:
        def __init__(self, backend_type: str):
            self.backend_type = backend_type

        def publish(self, destination, image):
            publications.append(self.backend_type)
            if image.getpixel((0, 0))[0] == 5:
                forced_images.append(image)

        def close(self):
            pass

    configurations = (
        _configuration("window"),
        _configuration("waveshare-13in3-e"),
        _configuration("image-server", (("default", _WIDE),)),
    )
    coordinator = DisplayPublicationCoordinator(
        configurations,
        lambda config: Backend(config.type),
        transient_capabilities={"window": False},
    )
    try:
        coordinator.publish(
            (4, 2),
            {
                _WIDE: Image.new("RGB", (4, 4), (1, 0, 0)),
                _PORTRAIT: Image.new("RGB", (4, 4), (1, 0, 0)),
            },
        )
        assert _wait_until(
            lambda: coordinator.acknowledgements
            == {
                "window": (4, 2),
                "waveshare-13in3-e": (4, 2),
                "image-server:default": (4, 2),
            }
        )
        assert coordinator.withdraw_destination("image-server:default")
        forced = coordinator.force_scheduled_publication(
            (4, 2),
            {
                _WIDE: Image.new("RGB", (16, 9), (5, 0, 0)),
                _PORTRAIT: Image.new("RGB", (16, 12), (5, 0, 0)),
            },
        )
        assert forced.wait(1).status is PublicationStatus.SUCCEEDED
        assert sorted(publications) == sorted(
            [
                "window",
                "waveshare-13in3-e",
                "image-server",
                "window",
                "waveshare-13in3-e",
            ]
        )
        assert coordinator.acknowledgements["image-server:default"] == (4, 2)
        assert coordinator.desired_identity == (4, 2)
        assert len(forced_images) == 2
        with pytest.raises(ValueError):
            forced_images[0].getpixel((0, 0))
    finally:
        coordinator.close()


def test_forced_completion_does_not_ack_a_newer_scheduled_identity() -> None:
    forced_entered, release_forced = Event(), Event()
    scheduled_entered, release_scheduled = Event(), Event()

    class Backend:
        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            if value == 2:
                forced_entered.set()
                assert release_forced.wait(2)
            elif value == 3:
                scheduled_entered.set()
                assert release_scheduled.wait(2)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend())
    try:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert coordinator.wait_for_publication((1, 0), timeout=1)
        forced = coordinator.force_scheduled_publication((1, 0), _images(_WIDE))
        assert forced_entered.wait(1)
        coordinator.publish((2, 0), {_WIDE: Image.new("RGB", (4, 4), (3, 0, 0))})
        release_forced.set()
        assert scheduled_entered.wait(1)
        assert forced.wait(1).status is PublicationStatus.SUCCEEDED
        assert coordinator.acknowledgements["window"] == (1, 0)
        release_scheduled.set()
        assert _wait_until(lambda: coordinator.acknowledgements["window"] == (2, 0))
    finally:
        release_forced.set()
        release_scheduled.set()
        coordinator.close()


def test_stale_forced_identity_is_rejected_without_backend_access(monkeypatch) -> None:
    publications: list[int] = []

    class Backend:
        def publish(self, _destination, image):
            publications.append(image.getpixel((0, 0))[0])

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend())
    try:
        coordinator.publish((2, 0), {_WIDE: Image.new("RGB", (4, 4), (7, 0, 0))})
        assert coordinator.wait_for_publication((2, 0), timeout=1)
        stale_images = _images(_WIDE, value=9)
        closes = _track_image_closes(monkeypatch, stale_images)

        stale = coordinator.force_scheduled_publication((1, 0), stale_images)

        assert stale.result.status is PublicationStatus.INVALID
        assert coordinator.desired_identity == (2, 0)
        assert coordinator.acknowledgements == {"window": (2, 0)}
        assert publications == [7]
        assert closes[id(stale_images[_WIDE])] == 1
    finally:
        coordinator.close()


def test_forced_publication_without_current_scheduled_identity_is_rejected(monkeypatch) -> None:
    factory_calls: list[bool] = []

    def factory(_configuration):
        factory_calls.append(True)
        raise AssertionError("invalid forced publication must not initialize a backend")

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), factory)
    images = _images(_WIDE)
    closes = _track_image_closes(monkeypatch, images)
    try:
        forced = coordinator.force_scheduled_publication((1, 0), images)
        assert forced.result.status is PublicationStatus.INVALID
        assert factory_calls == []
        assert closes[id(images[_WIDE])] == 1
    finally:
        coordinator.close()


def test_rejected_transient_request_releases_transferred_images_once(monkeypatch) -> None:
    coordinator = DisplayPublicationCoordinator(
        (_configuration("window"),),
        lambda _config: None,
        transient_capabilities={"window": False},
    )
    image = Image.new("RGB", (16, 9), (2, 0, 0))
    images = {_WIDE: image, _PORTRAIT: image}
    closes = _track_image_closes(monkeypatch, images)
    try:
        rejected = coordinator.publish_transient("window", {"window": _WIDE}, images)
        assert rejected.result.status is PublicationStatus.UNSUPPORTED
        assert closes[id(image)] == 1
    finally:
        coordinator.close()


@pytest.mark.parametrize(("forced", "fail"), [(False, False), (True, False), (False, True), (True, True)])
def test_one_shot_images_are_closed_exactly_once_on_success_or_failure(monkeypatch, forced: bool, fail: bool) -> None:
    publications: list[int] = []

    class Backend:
        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications.append(value)
            if fail and value == 2:
                raise DisplayBackendUpdateError("one-shot failed", recoverable=False)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator(
        (_configuration("window"),),
        lambda _config: Backend(),
        retry=False,
    )
    if forced:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert coordinator.wait_for_publication((1, 0), timeout=1)
    images = _images(_WIDE)
    closes = _track_image_closes(monkeypatch, images)
    try:
        if forced:
            operation = coordinator.force_scheduled_publication((1, 0), images)
        else:
            operation = coordinator.publish_transient("window", {"window": _WIDE}, images)

        result = operation.wait(1)

        assert result.status is (PublicationStatus.FAILED if fail else PublicationStatus.SUCCEEDED)
        assert closes[id(images[_WIDE])] == 1
        assert publications == ([1, 2] if forced else [2])
    finally:
        coordinator.close()


def test_forced_publication_fails_when_any_participating_destination_fails() -> None:
    publications: list[str] = []

    class Backend:
        def __init__(self, backend_type: str):
            self.backend_type = backend_type

        def publish(self, _destination, image):
            publications.append(self.backend_type)
            if image.getpixel((0, 0))[0] == 5 and self.backend_type == "window":
                raise DisplayBackendUpdateError("forced refresh failed", recoverable=False)

        def close(self):
            pass

    configurations = (_configuration("window"), _configuration("waveshare-13in3-e"))
    coordinator = DisplayPublicationCoordinator(configurations, lambda config: Backend(config.type), retry=False)
    try:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert _wait_until(lambda: coordinator.acknowledgements == {"window": (1, 0), "waveshare-13in3-e": (1, 0)})
        forced = coordinator.force_scheduled_publication((1, 0), _images(_WIDE, value=5))
        result = forced.wait(1)
        assert result.status is PublicationStatus.FAILED
        assert result.destinations == {
            "window": (False, "forced refresh failed"),
            "waveshare-13in3-e": (True, None),
        }
        assert publications.count("window") == 2
        assert publications.count("waveshare-13in3-e") == 2
    finally:
        coordinator.close()


@pytest.mark.parametrize("forced", [False, True])
def test_shutdown_retains_active_one_shot_image_until_backend_returns(monkeypatch, forced: bool) -> None:
    monkeypatch.setattr("refrain.display.coordinator._SHUTDOWN_TIMEOUT", 0.02)
    entered, release = Event(), Event()
    retained: list[Image.Image] = []
    backend_closed = Event()

    class Backend:
        def publish(self, _destination, image):
            retained.append(image)
            if image.getpixel((0, 0))[0] == 2:
                entered.set()
                assert release.wait(2)
                assert image.getpixel((0, 0)) == (2, 0, 0)

        def close(self):
            backend_closed.set()

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend())
    image = _images(_WIDE)[_WIDE]
    if forced:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert coordinator.wait_for_publication((1, 0), timeout=1)
        operation = coordinator.force_scheduled_publication((1, 0), {_WIDE: image})
    else:
        operation = coordinator.publish_transient("window", {"window": _WIDE}, {_WIDE: image})
    try:
        assert entered.wait(1)
        assert coordinator.close()
        assert image.getpixel((0, 0)) == (2, 0, 0)
        assert not backend_closed.is_set()
    finally:
        release.set()
        assert backend_closed.wait(1)
    assert operation.wait(1).status is PublicationStatus.SUCCEEDED


def test_shutdown_completes_active_one_shot_after_recoverable_failure(monkeypatch) -> None:
    monkeypatch.setattr("refrain.display.coordinator._SHUTDOWN_TIMEOUT", 0.02)
    entered, release = Event(), Event()

    class Backend:
        def publish(self, _destination, _image):
            entered.set()
            assert release.wait(2)
            raise DisplayBackendUpdateError("temporarily unavailable")

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend())
    operation = coordinator.publish_transient("window", {"window": _WIDE}, _images(_WIDE))
    try:
        assert entered.wait(1)
        assert coordinator.close()
        release.set()
        assert operation.wait(1).status is PublicationStatus.FAILED
    finally:
        release.set()
        coordinator.close()


def test_scheduled_pending_work_rejects_transient_admission() -> None:
    initialization_attempted = Event()

    class Backend:
        def publish(self, _destination, _image):
            pass

        def close(self):
            pass

    def factory(_config):
        initialization_attempted.set()
        raise DisplayBackendInitializationError("temporarily unavailable")

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), factory, retry=True)
    try:
        coordinator.publish((1, 0), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert initialization_attempted.wait(1)
        request = coordinator.publish_transient("window", {"window": _WIDE}, _images(_WIDE))
        assert request.result.status is PublicationStatus.BUSY
    finally:
        coordinator.close()


def test_forced_publication_busy_rejection_is_atomic() -> None:
    window_entered, release_window = Event(), Event()
    publications: list[tuple[str, int]] = []

    class Backend:
        def __init__(self, backend_type: str):
            self.backend_type = backend_type

        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications.append((self.backend_type, value))
            if self.backend_type == "window" and value == 1:
                window_entered.set()
                assert release_window.wait(2)

        def close(self):
            pass

    configurations = (
        _configuration("window"),
        _configuration("waveshare-13in3-e", (("waveshare-13in3-e", _PORTRAIT),)),
    )
    coordinator = DisplayPublicationCoordinator(configurations, lambda config: Backend(config.type))
    try:
        coordinator.publish(
            (1, 0),
            {
                _WIDE: Image.new("RGB", (4, 4), (1, 0, 0)),
                _PORTRAIT: Image.new("RGB", (4, 4), (1, 0, 0)),
            },
        )
        assert window_entered.wait(1)
        assert _wait_until(lambda: coordinator.acknowledgements["waveshare-13in3-e"] == (1, 0))
        forced = coordinator.force_scheduled_publication(
            (1, 0),
            {
                _WIDE: Image.new("RGB", (16, 9), (8, 0, 0)),
                _PORTRAIT: Image.new("RGB", (16, 12), (8, 0, 0)),
            },
        )
        assert forced.result.status is PublicationStatus.BUSY
        release_window.set()
        assert coordinator.wait_for_publication((1, 0), timeout=1)
        assert sorted(publications) == [("waveshare-13in3-e", 1), ("window", 1)]
    finally:
        release_window.set()
        coordinator.close()


def test_transient_failure_does_not_change_scheduled_desired_or_acknowledgement() -> None:
    publications: list[int] = []

    class Backend:
        def publish(self, _destination, image):
            value = image.getpixel((0, 0))[0]
            publications.append(value)
            if value == 2:
                raise DisplayBackendUpdateError("preview failed", recoverable=False)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((_configuration("window"),), lambda _config: Backend(), retry=False)
    try:
        coordinator.publish((5, 1), {_WIDE: Image.new("RGB", (4, 4), (1, 0, 0))})
        assert coordinator.wait_for_publication((5, 1), timeout=1)
        acknowledgement = coordinator.acknowledgements
        preview = coordinator.publish_transient("window", {"window": _WIDE}, _images(_WIDE))
        assert preview.wait(1).status is PublicationStatus.FAILED
        assert coordinator.desired_identity == (5, 1)
        assert coordinator.acknowledgements == acknowledgement
        assert publications == [1, 2]
    finally:
        coordinator.close()

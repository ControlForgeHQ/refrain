from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
from multiprocessing.connection import Client, Connection
from threading import Event, Thread

import pytest
from PIL import Image

from refrain import runtime_control as control_module
from refrain.config import DisplayBackendConfiguration, DisplayOutputConfiguration
from refrain.display import DisplayBackendUpdateError
from refrain.display.coordinator import (
    DisplayPublicationCoordinator,
    PublicationOperation,
    PublicationResult,
    PublicationStatus,
)
from refrain.geometry import ResolvedOutputSpecification
from refrain.runtime_control import (
    RuntimeAuthenticationError,
    RuntimeControlClient,
    RuntimeControlServer,
    RuntimeProtocolError,
    RuntimeUnavailable,
    RuntimeUnconfirmed,
)

SPEC = ResolvedOutputSpecification("16:9", (16, 9))


@pytest.fixture
def runtime(tmp_path):
    seen = []
    entered, release = Event(), Event()
    release.set()

    class Backend:
        def publish(self, destination, image):
            entered.set()
            assert release.wait(5)
            seen.append((destination.identifier, image.getpixel((0, 0))))

        def close(self):
            pass

    config = DisplayBackendConfiguration(
        "image-server",
        outputs=(DisplayOutputConfiguration("one", SPEC), DisplayOutputConfiguration("two", SPEC)),
    )
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend(), retry=False)
    coordinator.publish((1, 0), {SPEC: Image.new("RGB", SPEC.requested_output_size, (1, 2, 3))})
    assert coordinator.wait_for_publication((1, 0), 2)
    seen.clear()

    def refresh(admit):
        image = Image.new("RGB", SPEC.requested_output_size, (1, 2, 3))
        return admit((1, 0), {SPEC: image})

    path = tmp_path / "runtime.json"
    server = RuntimeControlServer(coordinator, path, refresh)
    server.start()
    try:
        yield path, coordinator, seen, entered, release, server
    finally:
        release.set()
        server.close()
        coordinator.close()


def _raw(path):
    metadata = json.loads(path.read_text())
    connection = Client(metadata["address"], family=metadata["family"])
    connection.send_bytes(json.dumps({"credential": metadata["credential"]}).encode())
    assert json.loads(connection.recv_bytes())["status"] == "authenticated"
    return connection


def test_discovery_push_and_refresh(runtime):
    path, coordinator, seen, _, _, _ = runtime
    client = RuntimeControlClient(path)
    destinations = client.discover()
    assert [record["identifier"] for record in destinations] == ["image-server:one", "image-server:two"]
    assert all(record["output_specification"] == SPEC and record["supports_transient"] for record in destinations)
    assert all(record["participating"] and record["available"] and not record["withdrawn"] for record in destinations)
    assert seen == []
    acknowledged = coordinator.acknowledgements
    image = Image.new("RGB", SPEC.requested_output_size, (9, 8, 7))
    try:
        specs = {record["identifier"]: SPEC for record in destinations}
        result = client.publish_transient("all", specs, {SPEC: image})
        assert result.status is PublicationStatus.SUCCEEDED
        assert set(result.destinations) == set(specs)
        assert sorted(seen) == [("one", (9, 8, 7)), ("two", (9, 8, 7))]
        assert coordinator.acknowledgements == acknowledged
        assert coordinator.desired_identity == (1, 0)
        seen.clear()
        assert client.refresh().status is PublicationStatus.SUCCEEDED
        assert sorted(seen) == [("one", (1, 2, 3)), ("two", (1, 2, 3))]
    finally:
        image.close()


def test_discovery_and_refresh_are_not_limited_by_transient_destinations(tmp_path, monkeypatch):
    seen = []

    class Backend:
        def publish(self, destination, image):
            seen.append(destination.identifier)

        def close(self):
            pass

    outputs = tuple(DisplayOutputConfiguration(f"output-{i}", SPEC) for i in range(130))
    config = DisplayBackendConfiguration("image-server", outputs=outputs)
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend(), retry=False)
    coordinator.publish((1, 0), {SPEC: Image.new("RGB", SPEC.requested_output_size)})
    assert coordinator.wait_for_publication((1, 0), 5)
    seen.clear()
    server = RuntimeControlServer(
        coordinator, tmp_path / "runtime.json", lambda admit: admit((1, 0), {SPEC: Image.new("RGB", (16, 9))})
    )
    server.start()
    try:
        monkeypatch.setattr(
            DisplayPublicationCoordinator,
            "destination_statuses",
            property(lambda self: pytest.fail("discovery must not construct an unbounded status snapshot")),
        )
        client = RuntimeControlClient(tmp_path / "runtime.json")
        records = client.discover()
        assert [r["identifier"] for r in records] == [f"image-server:output-{i}" for i in range(130)]
        result = client.refresh()
        assert result.status is PublicationStatus.SUCCEEDED
        assert len(result.destinations) == len(seen) == 130
    finally:
        server.close()
        coordinator.close()


def test_discovery_streams_long_destination_identifier(tmp_path):
    identifier = "😀" * 20_000

    class Backend:
        def publish(self, destination, image):
            pass

        def close(self):
            pass

    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration(identifier, SPEC),))
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend(), retry=False)
    coordinator.publish((1, 0), {SPEC: Image.new("RGB", SPEC.requested_output_size)})
    assert coordinator.wait_for_publication((1, 0), 5)
    server = RuntimeControlServer(
        coordinator, tmp_path / "runtime.json", lambda admit: admit((1, 0), {SPEC: Image.new("RGB", (16, 9))})
    )
    server.start()
    try:
        records = RuntimeControlClient(tmp_path / "runtime.json").discover()
        assert records[0]["identifier"] == f"image-server:{identifier}"
        assert records[0]["output_specification"] == SPEC
        result = RuntimeControlClient(tmp_path / "runtime.json").refresh()
        assert result.status is PublicationStatus.SUCCEEDED
        assert list(result.destinations) == [f"image-server:{identifier}"]
    finally:
        server.close()
        coordinator.close()


@pytest.mark.parametrize("identifier", ["normal", "😀" * 20_000])
def test_refresh_reports_large_backend_error_with_bounded_metadata(tmp_path, identifier):
    failure = Event()
    release = Event()
    error = "🚨" * 20_000

    class Backend:
        def publish(self, destination, image):
            if failure.is_set():
                assert release.wait(5)
                raise DisplayBackendUpdateError(error, recoverable=False)

        def close(self):
            pass

    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration(identifier, SPEC),))
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend(), retry=False)
    coordinator.publish((1, 0), {SPEC: Image.new("RGB", SPEC.requested_output_size)})
    assert coordinator.wait_for_publication((1, 0), 5)
    path = tmp_path / "runtime.json"
    server = RuntimeControlServer(coordinator, path, lambda admit: admit((1, 0), {SPEC: Image.new("RGB", (16, 9))}))
    server.start()
    try:
        failure.set()
        accepted = []

        def on_accepted():
            accepted.append(True)
            release.set()

        result = RuntimeControlClient(path).refresh(on_accepted=on_accepted)
        assert accepted == [True]
        assert result.status is PublicationStatus.FAILED
        success, message = result.destinations[f"image-server:{identifier}"]
        assert success is False
        assert message.endswith(" [truncated]")
        assert len(message) == control_module._MAX_ERROR_CHARS
        assert message.startswith(error[:100])
    finally:
        release.set()
        server.close()
        coordinator.close()


@pytest.mark.parametrize("size", [(3841, 1), (3840, 2401)])
def test_oversized_destination_discovery_and_refresh(tmp_path, size):
    seen = []
    oversized = ResolvedOutputSpecification("16:9", size)

    class Backend:
        def publish(self, destination, image):
            seen.append(image.size)

        def close(self):
            pass

    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("large", oversized),))
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend(), retry=False)
    coordinator.publish((1, 0), {oversized: Image.new("RGB", size)})
    assert coordinator.wait_for_publication((1, 0), 5)
    seen.clear()
    path = tmp_path / "runtime.json"
    server = RuntimeControlServer(coordinator, path, lambda admit: admit((1, 0), {oversized: Image.new("RGB", size)}))
    server.start()
    try:
        client = RuntimeControlClient(path)
        record = client.discover()[0]
        assert record["output_specification"] == oversized
        assert record["supports_transient"] is False
        with Image.new("RGB", size) as image:
            result = client.publish_transient(
                "image-server:large", {"image-server:large": oversized}, {oversized: image}
            )
        assert result.status is PublicationStatus.UNSUPPORTED
        assert not seen
        specification = {"aspect_ratio": "16:9", "size": list(size)}
        with _raw(path) as connection:
            connection.send_bytes(
                json.dumps(
                    {
                        "version": 1,
                        "operation": "publish",
                        "target": "all",
                        "specifications": {"image-server:large": specification},
                        "images": [{"specification": specification, "encoding": "png", "length": 1}],
                    }
                ).encode()
            )
            assert json.loads(connection.recv_bytes())["status"] == "unsupported"
        assert not seen
        assert client.refresh().status is PublicationStatus.SUCCEEDED
        assert seen == [size]
    finally:
        server.close()
        coordinator.close()


@pytest.mark.parametrize("target", ["all", "image-server:large"])
def test_unsupported_preflight_returns_before_sending_stale_image(tmp_path, monkeypatch, target):
    seen = []

    class Backend:
        def publish(self, destination, image):
            seen.append(destination.identifier)

        def close(self):
            pass

    large = ResolvedOutputSpecification("16:9", (3841, 1))
    stale = ResolvedOutputSpecification("16:9", (512, 256))
    config = DisplayBackendConfiguration("image-server", outputs=(DisplayOutputConfiguration("large", large),))
    coordinator = DisplayPublicationCoordinator((config,), lambda _: Backend(), retry=False)
    path = tmp_path / "runtime.json"
    server = RuntimeControlServer(coordinator, path, lambda _: None)
    server.start()
    sent_images = []
    send_bytes = Connection.send_bytes

    def observe_send(connection, data, *args, **kwargs):
        if len(data) > control_module._MAX_METADATA:
            sent_images.append(len(data))
        return send_bytes(connection, data, *args, **kwargs)

    monkeypatch.setattr(Connection, "send_bytes", observe_send)
    try:
        with Image.frombytes("RGB", stale.requested_output_size, os.urandom(512 * 256 * 3)) as image:
            result = RuntimeControlClient(path).publish_transient(target, {"image-server:large": stale}, {stale: image})
        assert result.status is PublicationStatus.UNSUPPORTED
        assert not sent_images
        assert not seen
    finally:
        server.close()
        coordinator.close()


def test_transient_raster_envelope():
    supports = control_module._supports_transient_spec
    assert supports(ResolvedOutputSpecification("16:10", (3840, 2400)))
    assert not supports(ResolvedOutputSpecification("16:10", (3841, 2400)))
    assert not supports(ResolvedOutputSpecification("16:10", (3840, 2401)))


def test_transient_destination_count_remains_bounded(runtime):
    path, _, seen, _, _, _ = runtime
    specification = {"aspect_ratio": "16:9", "size": [16, 9]}
    identifiers = [f"image-server:{i}" for i in range(65)]
    with _raw(path) as connection:
        connection.send_bytes(
            json.dumps(
                {
                    "version": 1,
                    "operation": "publish",
                    "target": identifiers,
                    "specifications": {identifier: specification for identifier in identifiers},
                    "images": [{"specification": specification, "encoding": "png", "length": 1}],
                }
            ).encode()
        )
        assert json.loads(connection.recv_bytes())["status"] == "invalid"
    assert not seen


def test_transient_aggregate_pixel_limit_is_checked_before_transfer(runtime, monkeypatch):
    path, _, seen, _, _, _ = runtime
    monkeypatch.setattr(control_module, "_MAX_TOTAL_PIXELS", 143)
    with Image.new("RGB", SPEC.requested_output_size) as image:
        with pytest.raises(RuntimeProtocolError, match="pixel limit"):
            RuntimeControlClient(path).publish_transient("image-server:one", {"image-server:one": SPEC}, {SPEC: image})
    assert not seen


@pytest.mark.parametrize("limit", ["image-count", "image-bytes", "total-bytes", "total-pixels"])
def test_server_rejects_resource_limits_before_image_transfer(runtime, limit):
    path, _, seen, _, _, server = runtime
    attempts = []
    server._transient_admission = lambda *args: attempts.append(args)
    sizes = [[16, 9], [17, 9]]
    lengths = [1, 1]
    if limit == "image-count":
        sizes.append([18, 9])
        lengths.append(1)
    elif limit == "image-bytes":
        lengths[0] = control_module._MAX_IMAGE_BYTES + 1
    elif limit == "total-bytes":
        lengths = [21 * 1024 * 1024, 21 * 1024 * 1024]
    else:
        sizes = [[3000, 2000], [3200, 2000]]
    specifications = [{"aspect_ratio": "16:9", "size": size} for size in sizes]
    identifiers = [f"image-server:{index}" for index in range(len(sizes))]
    request = {
        "version": 1,
        "operation": "publish",
        "target": identifiers,
        "specifications": dict(zip(identifiers, specifications, strict=True)),
        "images": [
            {"specification": spec, "encoding": "png", "length": length}
            for spec, length in zip(specifications, lengths, strict=True)
        ],
    }
    with _raw(path) as connection:
        connection.send_bytes(json.dumps(request).encode())
        assert json.loads(connection.recv_bytes())["status"] == "invalid"
    assert not attempts and not seen


@pytest.mark.parametrize("mode", ["L", "P", "RGBA"])
def test_client_rejects_non_rgb_before_transfer(runtime, mode):
    path, _, seen, _, _, _ = runtime
    with Image.new(mode, SPEC.requested_output_size) as image:
        with pytest.raises(RuntimeProtocolError, match="RGB"):
            RuntimeControlClient(path).publish_transient("image-server:one", {"image-server:one": SPEC}, {SPEC: image})
    assert not seen


@pytest.mark.parametrize("mode", ["L", "P", "RGBA", "1"])
def test_non_rgb_png_rejected_before_admission(runtime, mode):
    path, _, seen, _, _, server = runtime
    attempts = []
    server._transient_admission = lambda *args: attempts.append(args)
    with Image.new(mode, SPEC.requested_output_size) as image, io.BytesIO() as data:
        image.save(data, format="PNG")
        payload = data.getvalue()
    specification = {"aspect_ratio": "16:9", "size": [16, 9]}
    request = {
        "version": 1,
        "operation": "publish",
        "target": ["image-server:one"],
        "specifications": {"image-server:one": specification},
        "images": [{"specification": specification, "encoding": "png", "length": len(payload)}],
    }
    with _raw(path) as connection:
        connection.send_bytes(json.dumps(request).encode())
        connection.send_bytes(payload)
        assert json.loads(connection.recv_bytes())["status"] == "invalid"
    assert not attempts and not seen


def test_separate_process_can_authenticate_and_discover(runtime):
    path, _, _, _, _, _ = runtime
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from pathlib import Path; "
                "from refrain.runtime_control import RuntimeControlClient; "
                "print(len(RuntimeControlClient(Path(sys.argv[1])).discover()))"
            ),
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "2"


def test_withdrawn_discovery_and_publication(runtime):
    path, coordinator, seen, _, _, _ = runtime
    assert coordinator.withdraw_destination("image-server:two")
    client = RuntimeControlClient(path)
    records = client.discover()
    assert records[1]["withdrawn"] and not records[1]["participating"]
    with Image.new("RGB", SPEC.requested_output_size, (9, 8, 7)) as image:
        rejected = client.publish_transient("image-server:two", {"image-server:two": SPEC}, {SPEC: image})
        assert rejected.status is PublicationStatus.WITHDRAWN
        assert not seen
        result = client.publish_transient("all", {"image-server:one": SPEC}, {SPEC: image})
    assert result.status is PublicationStatus.SUCCEEDED
    assert seen == [("one", (9, 8, 7))]


def test_authentication_and_cleanup(runtime):
    path, _, _, _, _, server = runtime
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    metadata = json.loads(path.read_text())
    metadata["credential"] = "0" * 64
    path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeAuthenticationError):
        RuntimeControlClient(path).discover()
    # Do not delete metadata that was replaced after this listener started.
    server.close()
    assert path.exists()
    path.unlink()
    with pytest.raises(RuntimeUnavailable):
        RuntimeControlClient(path).discover()


def test_metadata_cannot_redirect_client_to_arbitrary_endpoint(runtime, monkeypatch):
    path, _, _, _, _, _ = runtime
    metadata = json.loads(path.read_text())
    metadata["address"] = r"\\.\pipe\unrelated" if os.name == "nt" else str(path.parent / "unrelated.sock")
    path.write_text(json.dumps(metadata))
    attempted = []
    monkeypatch.setattr(control_module, "Client", lambda *args, **kwargs: attempted.append(args))
    with pytest.raises(RuntimeProtocolError, match="endpoint"):
        RuntimeControlClient(path).discover()
    assert not attempted


@pytest.mark.skipif(os.name == "nt", reason="Unix mode bits")
def test_client_refuses_insecure_or_symlink_metadata(runtime):
    path, _, _, _, _, _ = runtime
    path.chmod(0o644)
    with pytest.raises(RuntimeProtocolError, match="not private"):
        RuntimeControlClient(path).discover()
    path.chmod(0o600)
    link = path.parent / "link"
    link.symlink_to(path)
    with pytest.raises(RuntimeUnavailable):
        RuntimeControlClient(link).discover()


def test_stalled_unauthenticated_connections_are_bounded(runtime, monkeypatch):
    path, _, _, _, _, server = runtime
    monkeypatch.setattr(control_module, "_AUTH_TIMEOUT", 0.5)
    metadata = json.loads(path.read_text())
    clients = [Client(metadata["address"], family=metadata["family"]) for _ in range(2)]
    try:
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            with server._lock:
                active = len(server._handlers)
            if active == 2:
                break
            time.sleep(0.005)
        assert active == 2
        with pytest.raises(RuntimeUnavailable):
            RuntimeControlClient(path).discover()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                assert len(RuntimeControlClient(path).discover()) == 2
                break
            except (RuntimeUnavailable, RuntimeProtocolError, ConnectionError):
                time.sleep(0.02)
        else:
            pytest.fail("stalled handshakes did not release their bounded slots")
    finally:
        for connection in clients:
            connection.close()


@pytest.mark.skipif(os.name == "nt", reason="Unix stream framing")
def test_partial_authentication_frame_has_absolute_deadline(runtime, monkeypatch):
    path, _, _, _, _, _ = runtime
    monkeypatch.setattr(control_module, "_AUTH_TIMEOUT", 0.2)
    metadata = json.loads(path.read_text())
    sockets = []
    try:
        for _ in range(2):
            peer = socket.socket(socket.AF_UNIX)
            peer.connect(metadata["address"])
            peer.sendall(b"\x00")
            sockets.append(peer)
        time.sleep(0.4)
        assert len(RuntimeControlClient(path).discover()) == 2
    finally:
        for peer in sockets:
            peer.close()


def test_close_returns_running_refresh_handler_for_ownership_retention(tmp_path):
    entered, release = Event(), Event()
    coordinator = DisplayPublicationCoordinator((), lambda _: None)

    def refresh(_admit):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("stopped")

    path = tmp_path / "runtime.json"
    server = RuntimeControlServer(coordinator, path, refresh)
    server.start()
    connection = _raw(path)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert entered.wait(1)
        pending = server.close()
        assert pending and all(isinstance(worker, Thread) for worker in pending)
        release.set()
        for worker in pending:
            worker.join(2)
            assert not worker.is_alive()
    finally:
        release.set()
        connection.close()
        server.close()
        coordinator.close()


@pytest.mark.parametrize("shutdown", [False, True])
def test_refresh_admission_guard_rejects_disconnection_or_shutdown(runtime, tmp_path, shutdown):
    _, coordinator, seen, _, _, _ = runtime
    preparing, release, rejected = Event(), Event(), Event()

    def refresh(admit):
        image = Image.new("RGB", SPEC.requested_output_size)
        preparing.set()
        try:
            assert release.wait(5)
            return admit((1, 0), {SPEC: image})
        except control_module.RuntimeAdmissionRejected:
            with pytest.raises(ValueError):
                image.getpixel((0, 0))
            rejected.set()
            raise

    path = tmp_path / "guarded-runtime.json"
    server = RuntimeControlServer(coordinator, path, refresh)
    server.start()
    connection = _raw(path)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert preparing.wait(1)
        if shutdown:
            assert server.close()
        else:
            connection.close()
        release.set()
        assert rejected.wait(2)
        assert seen == []
    finally:
        release.set()
        connection.close()
        server.close()


def test_shutdown_event_rejects_transient_before_listener_close(runtime, tmp_path):
    _, coordinator, seen, _, _, _ = runtime
    shutdown = Event()
    path = tmp_path / "shutdown-runtime.json"
    server = RuntimeControlServer(
        coordinator, path, lambda _admit: pytest.fail("unexpected refresh"), shutdown_event=shutdown
    )
    server.start()
    shutdown.set()
    try:
        with Image.new("RGB", SPEC.requested_output_size) as image:
            result = RuntimeControlClient(path).publish_transient(
                "image-server:one", {"image-server:one": SPEC}, {SPEC: image}
            )
        assert result.status is PublicationStatus.STOPPING
        assert seen == []
    finally:
        server.close()


@pytest.mark.parametrize("raise_error", [False, True])
def test_transient_admission_callback_owns_images_even_on_exception(runtime, tmp_path, raise_error):
    _, coordinator, seen, _, _, _ = runtime
    retained = []
    path = tmp_path / "admission.json"

    def admit(target, specifications, images, _guard):
        assert not server._lock.locked()
        assert target == ["image-server:one"]
        assert specifications == {"image-server:one": SPEC}
        retained.extend(images.values())
        assert retained[0].getpixel((0, 0)) == (9, 8, 7)
        if raise_error:
            raise RuntimeError("admission failed")
        return PublicationOperation(PublicationResult(PublicationStatus.INVALID, {}), done=True)

    server = RuntimeControlServer(coordinator, path, lambda _admit: None, transient_admission=admit)
    server.start()
    try:
        with Image.new("RGB", SPEC.requested_output_size, (9, 8, 7)) as image:
            result = RuntimeControlClient(path).publish_transient(
                "image-server:one", {"image-server:one": SPEC}, {SPEC: image}
            )
        assert result.status is (PublicationStatus.FAILED if raise_error else PublicationStatus.INVALID)
        assert retained[0].getpixel((0, 0)) == (9, 8, 7)
        assert seen == []
    finally:
        for image in retained:
            image.close()
        server.close()


@pytest.mark.parametrize("shutdown", [False, True])
def test_transient_guard_rejects_disconnection_or_shutdown(runtime, tmp_path, shutdown):
    _, coordinator, seen, _, _, _ = runtime
    preparing, release, rejected = Event(), Event(), Event()
    path = tmp_path / "guarded-transient.json"

    def admission(target, specifications, images, admit):
        assert not server._lock.locked()
        preparing.set()
        assert release.wait(5)
        try:
            return admit(target, specifications, images)
        except control_module.RuntimeAdmissionRejected:
            with pytest.raises(ValueError):
                next(iter(images.values())).getpixel((0, 0))
            rejected.set()
            raise

    server = RuntimeControlServer(coordinator, path, lambda _admit: None, transient_admission=admission)
    server.start()
    connection = _raw(path)
    try:
        import io

        with Image.new("RGB", SPEC.requested_output_size) as image, io.BytesIO() as data:
            image.save(data, format="PNG")
            payload = data.getvalue()
        specification = {"aspect_ratio": "16:9", "size": [16, 9]}
        message = {
            "version": 1,
            "operation": "publish",
            "target": ["image-server:one"],
            "specifications": {"image-server:one": specification},
            "images": [{"specification": specification, "encoding": "png", "length": len(payload)}],
        }
        connection.send_bytes(json.dumps(message).encode())
        connection.send_bytes(payload)
        connection.send_bytes(b'{"commit":true}')
        assert preparing.wait(1)
        if shutdown:
            assert server.close()
        else:
            connection.close()
        release.set()
        assert rejected.wait(2)
        assert seen == []
    finally:
        release.set()
        connection.close()
        server.close()


def test_shutdown_event_rejects_and_releases_prepared_refresh(runtime, tmp_path):
    _, coordinator, seen, _, _, _ = runtime
    shutdown, entered, release, rejected = Event(), Event(), Event(), Event()
    path = tmp_path / "shutdown-refresh.json"

    def refresh(admit):
        image = Image.new("RGB", SPEC.requested_output_size)
        entered.set()
        try:
            assert release.wait(5)
            return admit((1, 0), {SPEC: image})
        except control_module.RuntimeAdmissionRejected:
            with pytest.raises(ValueError):
                image.getpixel((0, 0))
            rejected.set()
            raise

    server = RuntimeControlServer(coordinator, path, refresh, shutdown_event=shutdown)
    server.start()
    connection = _raw(path)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert entered.wait(1)
        shutdown.set()
        release.set()
        assert rejected.wait(2)
        assert json.loads(connection.recv_bytes())["status"] == "stopping"
        assert seen == []
    finally:
        release.set()
        connection.close()
        server.close()


def test_refresh_waits_through_slow_preparation(runtime, tmp_path, monkeypatch):
    _, coordinator, seen, _, _, _ = runtime
    monkeypatch.setattr(control_module, "_IO_TIMEOUT", 0.1)
    monkeypatch.setattr(control_module, "_MAX_REQUEST_TIME", 1.0)
    path = tmp_path / "slow-refresh.json"

    def refresh(admit):
        time.sleep(0.25)
        return admit((1, 0), {SPEC: Image.new("RGB", SPEC.requested_output_size)})

    server = RuntimeControlServer(coordinator, path, refresh)
    server.start()
    try:
        assert RuntimeControlClient(path).refresh().status is PublicationStatus.SUCCEEDED
        assert len(seen) == 2
    finally:
        server.close()


@pytest.mark.skipif(os.name == "nt", reason="Unix socketpair")
def test_stalled_publication_response_is_bounded(monkeypatch):
    from multiprocessing.connection import Connection

    monkeypatch.setattr(control_module, "_IO_TIMEOUT", 0.2)
    left, right = socket.socketpair()
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    connection = Connection(left.detach())
    completed = Event()
    errors = []

    def slow_send(connection, _result):
        connection.send_bytes(b"x" * 1_000_000)

    def send():
        try:
            control_module.RuntimeControlServer._send_publication_response(
                connection, control_module.PublicationResult(PublicationStatus.ACCEPTED, {})
            )
        except OSError as error:
            errors.append(error)
        finally:
            completed.set()

    monkeypatch.setattr(control_module, "_send", slow_send)
    thread = Thread(target=send, daemon=True)
    try:
        thread.start()
        assert completed.wait(2)
        assert errors
    finally:
        right.close()
        thread.join(2)
        connection.close()


@pytest.mark.parametrize(
    "message",
    [
        {"version": 999, "operation": "discover"},
        {"version": 1, "operation": "unknown"},
        {"version": 1, "operation": "refresh", "identity": [1, 0]},
        {"version": 1, "operation": "publish", "target": [], "specifications": {}, "images": []},
    ],
)
def test_invalid_requests_never_publish(runtime, message):
    path, _, seen, _, _, _ = runtime
    with _raw(path) as connection:
        connection.send_bytes(json.dumps(message).encode())
        response = json.loads(connection.recv_bytes())
    assert response["status"] in {"invalid", "unsupported-protocol"}
    assert seen == []


def test_incomplete_payload_never_publishes(runtime):
    path, _, seen, _, _, _ = runtime
    spec = {"aspect_ratio": "16:9", "size": [16, 9]}
    request = {
        "version": 1,
        "operation": "publish",
        "target": ["image-server:one"],
        "specifications": {"image-server:one": spec},
        "images": [{"specification": spec, "encoding": "png", "length": 5}],
    }
    with _raw(path) as connection:
        connection.send_bytes(json.dumps(request).encode())
        connection.send_bytes(b"wrong")
        assert json.loads(connection.recv_bytes())["status"] == "invalid"
    assert seen == []


def test_disconnect_before_complete_transfer_never_publishes(runtime):
    path, _, seen, _, _, _ = runtime
    spec = {"aspect_ratio": "16:9", "size": [16, 9]}
    message = {
        "version": 1,
        "operation": "publish",
        "target": ["image-server:one"],
        "specifications": {"image-server:one": spec},
        "images": [{"specification": spec, "encoding": "png", "length": 5}],
    }
    connection = _raw(path)
    connection.send_bytes(json.dumps(message).encode())
    connection.close()
    # A new request can proceed and no incomplete image reaches a backend.
    for _ in range(100):
        try:
            assert len(RuntimeControlClient(path).discover()) == 2
            break
        except RuntimeUnavailable:
            Event().wait(0.01)
    else:
        pytest.fail("listener did not release disconnected client")
    assert seen == []


@pytest.mark.parametrize(
    ("encoding", "size", "payload"),
    [
        ("jpeg", [16, 9], b"abc"),
        ("png", [16, 9], b"abc"),
        ("png", [9000, 9], b"abc"),
    ],
)
def test_invalid_image_descriptor_or_payload_never_publishes(runtime, encoding, size, payload):
    path, _, seen, _, _, _ = runtime
    spec = {"aspect_ratio": "16:9", "size": size}
    message = {
        "version": 1,
        "operation": "publish",
        "target": ["image-server:one"],
        "specifications": {"image-server:one": spec},
        "images": [{"specification": spec, "encoding": encoding, "length": len(payload)}],
    }
    with _raw(path) as connection:
        connection.send_bytes(json.dumps(message).encode())
        if encoding == "png" and size == [16, 9]:
            connection.send_bytes(payload)
        assert json.loads(connection.recv_bytes())["status"] == ("unsupported" if size == [9000, 9] else "invalid")
    assert seen == []


def test_busy_and_changed_specification_are_rejected(runtime):
    path, _, seen, entered, release, _ = runtime
    client = RuntimeControlClient(path)
    wrong = ResolvedOutputSpecification("4:3", (16, 12))
    with Image.new("RGB", (16, 12)) as image:
        result = client.publish_transient("image-server:one", {"image-server:one": wrong}, {wrong: image})
        assert result.status is PublicationStatus.INVALID
    entered.clear()
    release.clear()
    connection = _raw(path)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert json.loads(connection.recv_bytes())["status"] == "accepted"
        assert entered.wait(1)
        with Image.new("RGB", SPEC.requested_output_size) as image:
            result = client.publish_transient("image-server:one", {"image-server:one": SPEC}, {SPEC: image})
        assert result.status is PublicationStatus.BUSY
        assert seen == []
    finally:
        release.set()
        connection.close()


def test_shutdown_removes_own_metadata_and_stale_endpoint(runtime):
    path, coordinator, _, _, _, server = runtime
    metadata = json.loads(path.read_text())
    server.close()
    assert not path.exists()
    if os.name == "nt":
        return
    assert not os.path.exists(metadata["address"])
    stale = path.parent / "refrain-0123456789abcdef.sock"
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(stale))
        path.write_text(json.dumps({"family": "AF_UNIX", "address": str(stale)}))
        replacement = RuntimeControlServer(coordinator, path, lambda _admit: None)
        replacement.start()
        try:
            assert not stale.exists()
            assert len(RuntimeControlClient(path).discover()) == 2
        finally:
            replacement.close()
    finally:
        sock.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux abstract Unix sockets")
def test_long_metadata_path_uses_abstract_socket(runtime, tmp_path):
    _, coordinator, _, _, _, _ = runtime
    path = tmp_path / ("long-directory-" + "x" * 100) / "endpoint.json"
    server = RuntimeControlServer(coordinator, path, lambda _admit: None)
    server.start()
    try:
        assert json.loads(path.read_text())["address"].startswith("\0")
        assert len(RuntimeControlClient(path).discover()) == 2
    finally:
        server.close()


def test_disconnect_after_admission_does_not_cancel(runtime):
    path, _, seen, entered, release, _ = runtime
    entered.clear()
    release.clear()
    connection = _raw(path)
    connection.send_bytes(b'{"version":1,"operation":"refresh"}')
    assert json.loads(connection.recv_bytes())["status"] == "accepted"
    assert entered.wait(1)
    connection.close()
    release.set()
    # A subsequent refresh must observe the original operation completing, not retry it.
    for _ in range(100):
        if len(seen) == 2:
            break
        Event().wait(0.01)
    assert sorted(seen) == [("one", (1, 2, 3)), ("two", (1, 2, 3))]


def test_client_unconfirmed_if_terminal_connection_is_lost(runtime, monkeypatch):
    path, _, seen, entered, release, _ = runtime
    entered.clear()
    release.clear()
    send = control_module._send

    def drop_terminal(connection, message):
        if message.get("status") == "succeeded" and isinstance(message.get("destinations"), dict):
            connection.close()
            raise OSError("terminal response lost")
        send(connection, message)

    def finish_after_acceptance():
        assert entered.wait(1)
        release.set()

    monkeypatch.setattr(control_module, "_send", drop_terminal)
    with pytest.raises(RuntimeUnconfirmed):
        RuntimeControlClient(path).refresh(on_accepted=finish_after_acceptance)
    release.set()
    for _ in range(100):
        if len(seen) == 2:
            break
        Event().wait(0.01)
    assert len(seen) == 2


def test_shutdown_retains_admitted_work_until_all_destinations_finish(runtime):
    path, _, seen, entered, release, server = runtime
    entered.clear()
    release.clear()
    connection = _raw(path)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert json.loads(connection.recv_bytes())["status"] == "accepted"
        assert entered.wait(1)
        connection.close()
        pending = server.close()
        assert pending
        release.set()
        for worker in pending:
            worker.join(2)
            assert not worker.is_alive()
        assert sorted(seen) == [("one", (1, 2, 3)), ("two", (1, 2, 3))]
    finally:
        release.set()
        connection.close()

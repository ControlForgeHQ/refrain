from __future__ import annotations

import errno
import http.client
import logging
import os
import signal
import socket
import struct
import subprocess
import sysconfig
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_publication_storage import _OUTPUT, _image, _metadata, _store

import refrain.image_server as image_server
from refrain.image_server_config import ImageServerConfiguration
from refrain.publication_metadata import finalize_publication_metadata
from refrain.publication_storage import PublicationStorageError, PublicationStore


@pytest.fixture
def service(tmp_path: Path):
    config = ImageServerConfiguration(tmp_path / "config.yaml", ("screen", "other"), tmp_path / "publish", port=0)
    server = image_server.create_server(config)
    thread = threading.Thread(target=image_server.run, args=(server,), daemon=True)
    thread.start()
    yield server
    server.stopping.set()
    thread.join(3)
    assert not thread.is_alive()


def _request(server, path="/destination/screen/current", method="GET", headers=None):
    connection = http.client.HTTPConnection(*server.server_address[:2], timeout=3)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _publish(server, publication_id="first", destination="screen", transient=False, value=0):
    if transient:
        metadata = finalize_publication_metadata(
            publication_type="transient",
            publication_id=publication_id,
            published_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
            destination_id=destination,
            output_specification=_OUTPUT,
        )
    else:
        metadata = _metadata(publication_id, destination)
    with _image(value) as image:
        _store(server.config.publication_root).publish(destination, image, metadata, audience="internal")


def test_publication_http_semantics_and_replacement(service, caplog):
    with caplog.at_level(logging.DEBUG):
        assert _request(service)[0] == 503
        _publish(service)
        dataset = service.config.read_current("screen")
        status, headers, body = _request(service)
        assert status == 200 and body == dataset.image
        assert headers["Content-Type"] == "image/png"
        assert int(headers["Content-Length"]) == len(body)
        assert headers["ETag"] == f'"{dataset.manifest.image_sha256}"'
        assert headers["Cache-Control"] == "no-cache"
        head = _request(service, method="HEAD")
        assert head[0] == 200 and head[1]["Content-Length"] == str(len(body)) and head[2] == b""
        for value in (headers["ETag"], "W/" + headers["ETag"], f'"other", W/{headers["ETag"]}', "*"):
            result = _request(service, headers={"If-None-Match": value})
            assert result[0] == 304 and result[2] == b""
        assert _request(service, headers={"If-None-Match": '"different"'})[0] == 200
        _publish(service, "second", transient=True)
        assert _request(service, headers={"If-None-Match": headers["ETag"]})[0] == 304
        _publish(service, "third", transient=True, value=5)
        assert _request(service, headers={"If-None-Match": headers["ETag"]})[0] == 200
        (service.config.publication_root / "screen" / "third.png").write_bytes(b"damaged")
        assert _request(service, headers={"If-None-Match": "*"})[0] == 503
        assert _request(service)[0] == 503
        _publish(service, "other-event", "other")
        assert _request(service, "/destination/other/current")[0] == 200
        assert "Publication recovered for destination screen" in caplog.text
        assert sum("invalid or inaccessible" in r.message for r in caplog.records) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/destination/Screen/current",
        "/destination/missing/current",
        "/destination/../current",
        "/destination/%73creen/current",
        "/destination/screen/current?x=1",
        "//destination/screen/current",
    ],
)
def test_unrecognized_paths(service, path):
    status, headers, body = _request(service, path)
    assert status == 404 and headers["Cache-Control"] == "no-store" and not body


def test_methods_repeated_headers_and_malformed_request(service):
    _publish(service)
    status, headers, _ = _request(service, method="POST")
    assert status == 405 and headers["Allow"] == "GET, HEAD"
    status, headers, _ = _request(service, method="POST", headers={"Content-Length": "2"})
    assert status == 405 and headers["Allow"] == "GET, HEAD"
    etag = _request(service)[1]["ETag"]
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(
            f"GET /destination/screen/current HTTP/1.1\r\nHost: localhost\r\n"
            f'If-None-Match: "other"\r\nIf-None-Match: W/{etag}\r\n\r\n'.encode()
        )
        assert b" 304 " in connection.recv(4096)
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET / HTTP/1.1\r\nBad Header\r\n\r\n")
        assert b" 400 " in connection.recv(4096)
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET / HTTP/1.1 extra\r\n\r\n")
        response = connection.recv(4096)
        assert b" 400 " in response and b"Cache-Control: no-store" in response
        assert b"extra" not in response
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nExpect: 100-continue\r\n\r\n")
        response = connection.recv(4096)
        assert b" 417 " in response and b" 100 " not in response


@pytest.mark.parametrize(
    "headers",
    [
        b"",
        b"Host: a\r\nHost: b\r\n",
        b"Host: bad host\r\n",
        b"Host: [::1\r\n",
        b"Host: localhost:99999\r\n",
        b"Host: localhost\r\nContent-Length: 0\r\nContent-Length: 0\r\n",
        b"Host: localhost\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n",
    ],
)
def test_invalid_host_or_body_framing_is_rejected(service, headers):
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET /destination/screen/current HTTP/1.1\r\n" + headers + b"\r\n")
        response = connection.recv(4096)
        assert b" 400 " in response and b"Cache-Control: no-store" in response


def test_half_closed_client_still_receives_response(service):
    _publish(service)
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET /destination/screen/current HTTP/1.1\r\nHost: localhost\r\n\r\n")
        connection.shutdown(socket.SHUT_WR)
        response = bytearray()
        while chunk := connection.recv(4096):
            response.extend(chunk)
    assert b" 200 " in response and b"\x89PNG" in response


def test_complete_body_is_received_and_oversize_is_rejected(service):
    _publish(service)
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET /destination/screen/current HTTP/1.1\r\nHost: localhost\r\nContent-Length: 5\r\n\r\n")
        connection.sendall(b"hello")
        assert b" 200 " in connection.recv(4096)
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 65537\r\n\r\n")
        assert b" 413 " in connection.recv(4096)
    with socket.create_connection(service.server_address[:2], timeout=2) as connection:
        connection.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n")
        assert b" 501 " in connection.recv(4096)


def test_body_reception_shares_absolute_request_deadline(service, monkeypatch):
    monkeypatch.setattr(image_server, "RECEPTION_TIMEOUT", 0.3)
    with socket.create_connection(service.server_address[:2], timeout=1) as connection:
        connection.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 10\r\n\r\n")
        start = time.monotonic()
        for _ in range(10):
            try:
                connection.sendall(b"x")
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                break
            time.sleep(0.06)
        try:
            assert connection.recv(1) == b""
        except (ConnectionAbortedError, ConnectionResetError):
            pass
        assert 0.24 <= time.monotonic() - start < 0.8


def test_request_deadline_is_absolute_under_dribble(service, monkeypatch):
    monkeypatch.setattr(image_server, "RECEPTION_TIMEOUT", 0.3)
    with socket.create_connection(service.server_address[:2], timeout=1) as connection:
        start = time.monotonic()
        for _ in range(10):
            try:
                connection.sendall(b"x")
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                break
            time.sleep(0.06)
        try:
            assert connection.recv(1) == b""
        except (ConnectionAbortedError, ConnectionResetError):
            pass
        assert 0.24 <= time.monotonic() - start < 0.8


def test_blocked_verifier_is_daemon_and_cannot_succeed_after_shutdown(service, monkeypatch):
    _publish(service)
    dataset = service.config.read_current("screen")
    entered, release = threading.Event(), threading.Event()

    def blocked(_self, _destination, **_kwargs):
        entered.set()
        release.wait(3)
        return dataset

    monkeypatch.setattr(ImageServerConfiguration, "read_current", blocked)
    monkeypatch.setattr(image_server, "SHUTDOWN_TIMEOUT", 0.15)
    connection = socket.create_connection(service.server_address[:2], timeout=2)
    connection.sendall(b"GET /destination/screen/current HTTP/1.1\r\nHost: localhost\r\n\r\n")
    assert entered.wait(1)
    workers = [thread for thread in threading.enumerate() if thread.name == "image-verification"]
    assert workers and all(thread.daemon for thread in workers)
    service.stopping.set()
    assert connection.recv(1024) == b""
    release.set()
    connection.close()


def test_verification_timeout_discards_late_result(service, monkeypatch, caplog):
    _publish(service)
    dataset = service.config.read_current("screen")
    entered, release = threading.Event(), threading.Event()

    def blocked(_self, _destination, **_kwargs):
        entered.set()
        release.wait(3)
        return dataset

    monkeypatch.setattr(ImageServerConfiguration, "read_current", blocked)
    monkeypatch.setattr(image_server, "VERIFICATION_TIMEOUT", 0.15)
    with caplog.at_level(logging.DEBUG):
        assert _request(service)[0] == 503
        assert entered.is_set()
        assert _request(service)[0] == 503
    assert "Publication verification timed out" in caplog.text
    release.set()


def test_verification_worker_does_not_start_after_deadline(service, monkeypatch):
    delayed = []
    calls = []
    original_start = threading.Thread.start

    def delay_worker(thread):
        if thread.name == "image-verification":
            delayed.append(thread)
        else:
            original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", delay_worker)
    monkeypatch.setattr(image_server, "VERIFICATION_TIMEOUT", 0.1)
    monkeypatch.setattr(ImageServerConfiguration, "read_current", lambda *_args, **_kwargs: calls.append(1))
    assert _request(service)[0] == 503
    assert len(delayed) == 1
    delayed[0].run()
    assert not calls
    assert service.verification.acquire(blocking=False)
    service.verification.release()


def test_reader_does_not_retry_after_verification_deadline(service, monkeypatch, caplog):
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def blocked(_self, _destination, *, create):
        calls.append(create)
        entered.set()
        release.wait(2)
        completed.set()
        raise PublicationStorageError("first attempt failed")

    monkeypatch.setattr(PublicationStore, "_destination", blocked)
    monkeypatch.setattr(image_server, "VERIFICATION_TIMEOUT", 0.15)
    with caplog.at_level(logging.DEBUG):
        try:
            assert _request(service)[0] == 503
            assert entered.is_set()
        finally:
            release.set()
        assert completed.wait(1)
        assert service.verification.acquire(timeout=1)
        service.verification.release()
    assert calls == [False]
    assert not service._failures
    assert "Publication verification cancelled or timed out" in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_worker_start_failure_releases_verification_slot(service, monkeypatch, caplog):
    original = threading.Thread.start

    def fail_worker(thread):
        if thread.name == "image-verification":
            raise RuntimeError("sensitive exception")
        original(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_worker)
    with caplog.at_level(logging.ERROR):
        assert _request(service)[0] == 503
    assert service.verification.acquire(blocking=False)
    service.verification.release()
    assert "Cannot start publication verification worker" in caplog.text
    assert "sensitive exception" not in caplog.text


def test_reset_clients_release_handlers_but_not_blocked_verifier(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(_self, _destination, **_kwargs):
        entered.set()
        release.wait(3)
        raise PublicationStorageError("blocked")

    monkeypatch.setattr(ImageServerConfiguration, "read_current", blocked)
    first = socket.create_connection(service.server_address[:2], timeout=2)
    second = None
    try:
        first.sendall(b"GET /destination/screen/current HTTP/1.1\r\nHost: localhost\r\n\r\n")
        assert entered.wait(1)
        second = socket.create_connection(service.server_address[:2], timeout=2)
        second.sendall(b"GET /destination/other/current HTTP/1.1\r\nHost: localhost\r\n\r\n")
        deadline = time.monotonic() + 2
        with service._condition:
            while len(service._clients) < 2:
                assert time.monotonic() < deadline
                service._condition.wait(0.02)
        first.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        second.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        first.close()
        second.close()
        with service._condition:
            while service._clients:
                assert time.monotonic() < deadline
                service._condition.wait(0.05)
        assert not service.verification.acquire(blocking=False)
    finally:
        release.set()
        first.close()
        if second is not None:
            second.close()


def test_failure_logging_does_not_disclose_untrusted_reader_error(service, monkeypatch, caplog):
    secret = "sensitive metadata and /private/path"
    errors = iter([secret, secret, secret + " changed"])

    def fail(_self, _destination, **_kwargs):
        raise PublicationStorageError(next(errors))

    monkeypatch.setattr(ImageServerConfiguration, "read_current", fail)
    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            assert _request(service)[0] == 503
    assert secret not in caplog.text
    assert sum("invalid or inaccessible" in record.message for record in caplog.records) == 2


def test_inaccessible_destination_is_isolated_and_recovers(service, monkeypatch, caplog):
    _publish(service)
    _publish(service, "other-event", "other")
    original = ImageServerConfiguration.read_current
    failing = True

    def read(config, destination, **_kwargs):
        if destination == "screen" and failing:
            raise PublicationStorageError("cannot inspect publication") from PermissionError("private path")
        return original(config, destination)

    monkeypatch.setattr(ImageServerConfiguration, "read_current", read)
    with caplog.at_level(logging.DEBUG):
        assert _request(service)[0] == 503
        assert _request(service)[0] == 503
        assert _request(service, "/destination/other/current")[0] == 200
        failing = False
        assert _request(service)[0] == 200
    assert sum("invalid or inaccessible" in r.message for r in caplog.records) == 1
    assert "Publication recovered for destination screen" in caplog.text
    assert "private path" not in caplog.text


def test_requests_do_not_modify_publication_files(service):
    _publish(service)
    root = service.config.publication_root
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    for method in ("GET", "HEAD"):
        assert _request(service, method=method)[0] == 200
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert before == after


def test_concurrent_publication_replacement_uses_only_verified_images(service):
    _publish(service, "initial", value=0)
    first = service.config.read_current("screen").image
    _publish(service, "other-image", value=5)
    second = service.config.read_current("screen").image
    start = threading.Event()
    errors = []

    def publish():
        try:
            assert start.wait(2)
            for index in range(12):
                _publish(service, f"replacement-{index}", transient=True, value=5 if index % 2 else 0)
        except Exception as error:
            errors.append(error)

    writer = threading.Thread(target=publish, daemon=True)
    writer.start()
    start.set()
    for _ in range(25):
        status, _, body = _request(service)
        assert status in (200, 503)
        assert (status == 200 and body in (first, second)) or (status == 503 and not body)
    writer.join(5)
    assert not writer.is_alive() and not errors


def test_write_inactivity_terminates_stalled_loopback(service, monkeypatch):
    _publish(service)
    dataset = service.config.read_current("screen")
    monkeypatch.setattr(ImageServerConfiguration, "read_current", lambda _self, _dest, **_kwargs: dataset)
    monkeypatch.setattr(image_server, "WRITE_INACTIVITY_TIMEOUT", 0.15)
    original = image_server._SocketWriter.write

    def send_large(self, data):
        if data.startswith(b"\x89PNG"):
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            data = b"x" * (16 * 1024 * 1024)
        return original(self, data)

    monkeypatch.setattr(image_server._SocketWriter, "write", send_large)
    with socket.create_connection(service.server_address[:2], timeout=2) as client:
        client.sendall(b"GET /destination/screen/current HTTP/1.1\r\nHost: localhost\r\n\r\n")
        deadline = time.monotonic() + 2
        with service._condition:
            while not service._clients:
                assert time.monotonic() < deadline
                service._condition.wait(0.01)
            while service._clients:
                assert time.monotonic() < deadline
                service._condition.wait(0.05)


def test_response_deadline_starts_on_first_write_and_bounds_progress(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(image_server.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(image_server, "RESPONSE_TIMEOUT", 1.0)

    class SlowConnection:
        def settimeout(self, timeout):
            assert timeout > 0

        def send(self, data):
            clock[0] += 0.4
            return 1

    writer = image_server._SocketWriter(SlowConnection())
    clock[0] = 100
    with pytest.raises(TimeoutError):
        writer.write(b"12345")
    assert clock[0] < 102


def _executable():
    name = "refrain-image-server.exe" if os.name == "nt" else "refrain-image-server"
    return str(Path(sysconfig.get_path("scripts")) / name)


def _write_config(tmp_path, port):
    config = tmp_path / "config.yaml"
    config.write_text(
        "destinations:\n  - id: screen\n    type: publish\n"
        f"storage:\n  publish: {tmp_path / 'publish'}\n"
        f"image-server:\n  destinations: [screen]\n  port: {port}\n",
        encoding="utf-8",
    )
    return config


def test_foreground_process_failure_exit_codes(tmp_path):
    executable = _executable()
    missing = subprocess.run([executable, "--config", str(tmp_path / "missing.yaml")], capture_output=True, timeout=5)
    assert missing.returncode == 78
    with socket.socket() as reservation:
        if os.name == "nt":
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reservation.bind(("127.0.0.1", 0))
        reservation.listen()
        port = reservation.getsockname()[1]
        config = _write_config(tmp_path, port)
        occupied = subprocess.run([executable, "--config", str(config)], capture_output=True, timeout=5)
        assert occupied.returncode == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal handling for foreground process")
def test_foreground_process_shutdown_exit_code(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    config = _write_config(tmp_path, port)
    process = subprocess.Popen([_executable(), "--config", str(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while True:
            assert process.poll() is None
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                assert time.monotonic() < deadline
                time.sleep(0.02)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=6)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2)


def test_handler_capacity_is_bounded(service):
    clients = []
    try:
        for _ in range(image_server.HANDLER_LIMIT):
            clients.append(socket.create_connection(service.server_address[:2], timeout=2))
        deadline = time.monotonic() + 2
        with service._condition:
            while len(service._clients) < image_server.HANDLER_LIMIT:
                remaining = deadline - time.monotonic()
                assert remaining > 0
                service._condition.wait(min(remaining, 0.02))
        with socket.create_connection(service.server_address[:2], timeout=2) as extra:
            assert b" 503 " in extra.recv(1024)
    finally:
        for client in clients:
            client.close()


def test_transmission_does_not_hold_verification_slot(service, monkeypatch):
    _publish(service)
    entered, release = threading.Event(), threading.Event()
    original = image_server._SocketWriter.write

    def blocked_write(self, data):
        if data.startswith(b"\x89PNG"):
            entered.set()
            assert release.wait(2)
        return original(self, data)

    monkeypatch.setattr(image_server._SocketWriter, "write", blocked_write)
    results = []
    client = threading.Thread(target=lambda: results.append(_request(service)), daemon=True)
    client.start()
    try:
        assert entered.wait(1)
        assert _request(service, method="HEAD")[0] == 200
    finally:
        release.set()
        client.join(2)
    assert results[0][0] == 200


def test_serialized_verification_and_waiting_shutdown(service, monkeypatch):
    _publish(service)
    dataset = service.config.read_current("screen")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked(_self, _destination, **_kwargs):
        calls.append(1)
        entered.set()
        release.wait(2)
        return dataset

    monkeypatch.setattr(ImageServerConfiguration, "read_current", blocked)
    monkeypatch.setattr(image_server, "SHUTDOWN_TIMEOUT", 0.2)
    first = threading.Thread(target=lambda: _request(service), daemon=True)
    first.start()
    assert entered.wait(1)
    second_result = []
    second = threading.Thread(target=lambda: second_result.append(_request(service)[0]), daemon=True)
    second.start()
    deadline = time.monotonic() + 1
    while len(service._clients) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    service.stopping.set()
    second.join(1)
    assert second_result == [503] and len(calls) == 1
    release.set()
    first.join(2)


def test_listener_accept_failure_is_fatal(service, monkeypatch):
    def fail():
        raise OSError("listener failed")

    monkeypatch.setattr(service, "get_request", fail)
    with pytest.raises(OSError, match="listener failed"):
        service._handle_request_noblock()


@pytest.mark.parametrize("error_number", [errno.ECONNABORTED, errno.ECONNRESET, errno.EINTR, errno.EAGAIN])
def test_aborted_accept_is_not_fatal(service, monkeypatch, error_number):
    def fail():
        raise OSError(error_number, "transient accept failure")

    monkeypatch.setattr(service, "get_request", fail)
    service._handle_request_noblock()
    assert not service.stopping.is_set()


def test_main_reports_service_failure(monkeypatch, tmp_path):
    config = ImageServerConfiguration(tmp_path / "config", ("screen",), tmp_path / "publish", port=0)
    monkeypatch.setattr(image_server, "load_image_server_config", lambda _: config)
    server = image_server.create_server(config)
    monkeypatch.setattr(image_server, "create_server", lambda _: server)
    monkeypatch.setattr(server, "handle_request", lambda: (_ for _ in ()).throw(OSError("failure")))
    assert image_server.main([]) == 1
    assert server.socket.fileno() == -1


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_supported_listener_addresses(tmp_path, host):
    config = ImageServerConfiguration(tmp_path / "config", ("screen",), tmp_path / "publish", host=host, port=0)
    try:
        server = image_server.create_server(config)
    except OSError as error:
        if host == "::1":
            pytest.skip(f"IPv6 loopback unavailable: {error}")
        raise
    server.server_close()

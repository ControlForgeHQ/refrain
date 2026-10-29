from __future__ import annotations

import hashlib
import http.client
import io
import socket
import threading
import time
from threading import Event

import pytest
from PIL import Image

from refrain.display import (
    DisplayBackend,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
    create_display_backend,
)
from refrain.display.image_server import ImageServerDisplayBackend


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(port: int, method: str = "GET", path: str = "/display/current", headers: dict[str, str] | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def png_bytes(image: Image.Image) -> bytes:
    with io.BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


def backend_at_available_port() -> tuple[ImageServerDisplayBackend, int]:
    port = available_port()
    return ImageServerDisplayBackend(port=port), port


def wait_for_handler_threads(backend: ImageServerDisplayBackend) -> tuple[threading.Thread, ...]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        threads = getattr(backend._server, "_threads", ())
        if isinstance(threads, list) and threads and all(thread.is_alive() for thread in threads):
            return tuple(threads)
        time.sleep(0.01)
    raise AssertionError("the server did not start a request-handler thread")


def test_factory_backend_serves_png_and_preserves_caller_image() -> None:
    port = available_port()
    backend = create_display_backend("image-server", image_server_port=port)
    assert isinstance(backend, DisplayBackend)
    assert isinstance(backend, ImageServerDisplayBackend)
    image = Image.new("RGB", (13, 7), (15, 72, 131))
    before = image.mode, image.size, image.tobytes()
    try:
        assert request(port)[0] == 503

        backend.update(image)

        status, headers, body = request(port)
        assert status == 200
        assert headers["Content-Type"] == "image/png"
        assert int(headers["Content-Length"]) == len(body)
        assert headers["ETag"] == f'"{hashlib.sha256(body).hexdigest()}"'
        with Image.open(io.BytesIO(body)) as served:
            assert served.format == "PNG"
            assert served.mode == "RGB"
            assert served.size == (13, 7)
            assert served.getpixel((0, 0)) == (15, 72, 131)
        assert (image.mode, image.size, image.tobytes()) == before
    finally:
        image.close()
        backend.close()


def test_conditional_requests_and_replacement_use_content_etags() -> None:
    backend, port = backend_at_available_port()
    try:
        backend.update(Image.new("RGB", (2, 2), "red"))
        first_status, first_headers, first_body = request(port)
        first_tag = first_headers["ETag"]

        for condition in (first_tag, f"W/{first_tag}", f'"unrelated", {first_tag}', "*"):
            status, headers, body = request(port, headers={"If-None-Match": condition})
            assert status == 304
            assert headers["ETag"] == first_tag
            assert "Content-Length" not in headers
            assert body == b""

        backend.update(Image.new("RGB", (2, 2), "blue"))
        second_status, second_headers, second_body = request(port, headers={"If-None-Match": first_tag})

        assert first_status == second_status == 200
        assert first_body != second_body
        assert second_headers["ETag"] != first_tag
        assert second_headers["ETag"] == f'"{hashlib.sha256(second_body).hexdigest()}"'
    finally:
        backend.close()


def test_browser_refresh_uses_a_new_connection_after_each_response() -> None:
    backend, port = backend_at_available_port()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    first_image = Image.new("RGB", (2, 2), "red")
    second_image = Image.new("RGB", (2, 2), "blue")
    try:
        backend.update(first_image)
        connection.request("GET", "/display/current")
        first_response = connection.getresponse()
        first_body = first_response.read()

        assert first_response.status == 200
        assert first_response.version == 10
        assert connection.sock is None

        backend.update(second_image)
        connection.request("GET", "/display/current")
        second_response = connection.getresponse()
        second_body = second_response.read()

        assert second_response.status == 200
        assert second_body != first_body
    finally:
        first_image.close()
        second_image.close()
        connection.close()
        backend.close()


def test_failed_image_encoding_preserves_previous_representation(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, port = backend_at_available_port()
    image = Image.new("RGB", (2, 2), "green")
    try:
        backend.update(image)
        previous = request(port)

        def fail_save(*_args: object, **_kwargs: object) -> None:
            raise OSError("encoding failure")

        monkeypatch.setattr(Image.Image, "save", fail_save)
        with pytest.raises(DisplayBackendUpdateError, match="encoding failure"):
            backend.update(Image.new("RGB", (3, 3), "orange"))

        current = request(port)
        assert current[0] == previous[0] == 200
        assert current[1]["ETag"] == previous[1]["ETag"]
        assert current[2] == previous[2]
    finally:
        image.close()
        backend.close()


def test_unsupported_methods_paths_and_malformed_requests_do_not_stop_service() -> None:
    backend, port = backend_at_available_port()
    try:
        backend.update(Image.new("RGB", (1, 1), "white"))

        status, headers, _body = request(port, method="POST")
        assert status == 405
        assert headers["Allow"] == "GET"
        assert request(port, method="HEAD")[0] == 405
        assert request(port, path="/")[0] == 404
        assert request(port, path="/display/current?path=../")[0] == 404

        with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
            connection.sendall(b"not an HTTP request\r\n\r\n")
            malformed_response = bytearray()
            while chunk := connection.recv(1024):
                malformed_response.extend(chunk)
            assert malformed_response

        assert request(port)[0] == 200
    finally:
        backend.close()


def test_concurrent_updates_and_requests_observe_complete_matching_representations() -> None:
    backend, port = backend_at_available_port()
    images = [Image.new("RGB", (80, 60), color) for color in ("red", "blue")]
    encoded = {png_bytes(image) for image in images}
    expected_tags = {f'"{hashlib.sha256(body).hexdigest()}"' for body in encoded}
    start = Event()
    failures: list[str] = []

    def replace_images() -> None:
        start.wait()
        for index in range(50):
            backend.update(images[index % len(images)])

    def fetch_images() -> None:
        start.wait()
        for _ in range(50):
            status, headers, body = request(port)
            if status != 200 or body not in encoded or headers.get("ETag") not in expected_tags:
                failures.append("request observed an incomplete or unknown representation")
                return
            if headers["ETag"] != f'"{hashlib.sha256(body).hexdigest()}"':
                failures.append("request observed a mismatched image and entity tag")
                return

    updater = threading.Thread(target=replace_images)
    clients = [threading.Thread(target=fetch_images) for _ in range(4)]
    try:
        backend.update(images[0])
        updater.start()
        for client in clients:
            client.start()
        start.set()
        updater.join(timeout=10)
        for client in clients:
            client.join(timeout=10)

        assert not updater.is_alive()
        assert all(not client.is_alive() for client in clients)
        assert failures == []
    finally:
        start.set()
        for thread in [updater, *clients]:
            if thread.ident is not None:
                thread.join(timeout=1)
        for image in images:
            image.close()
        backend.close()


def test_close_is_repeatable_releases_port_and_rejects_updates() -> None:
    port = available_port()
    backend = ImageServerDisplayBackend(port=port)
    backend.close()
    backend.close()

    with pytest.raises(OSError):
        request(port)
    with pytest.raises(DisplayBackendUpdateError, match="closed") as failure:
        backend.update(Image.new("RGB", (1, 1)))
    assert not failure.value.recoverable

    replacement = ImageServerDisplayBackend(port=port)
    replacement.close()


def test_close_joins_incomplete_request_handler_and_releases_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import refrain.display.image_server as image_server_module

    monkeypatch.setattr(image_server_module, "_REQUEST_LIFETIME", 0.1)
    backend, port = backend_at_available_port()
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.sendall(b"GET /display/current HTTP/1.1\r\n")
        handler_threads = wait_for_handler_threads(backend)

        started = time.monotonic()
        backend.close()

        assert time.monotonic() - started < 1
        assert all(not thread.is_alive() for thread in handler_threads)
        client.settimeout(0.2)
        assert client.recv(1) == b""


def test_disconnected_incomplete_client_does_not_leave_handler_running() -> None:
    backend, port = backend_at_available_port()
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.sendall(b"GET /display/current HTTP/1.1\r\n")
    handler_threads = wait_for_handler_threads(backend)

    client.close()
    handler_threads[0].join(timeout=1)
    try:
        assert not handler_threads[0].is_alive()
    finally:
        backend.close()


def test_total_request_lifetime_bounds_slow_trickling_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    import refrain.display.image_server as image_server_module

    monkeypatch.setattr(image_server_module, "_REQUEST_LIFETIME", 0.2)
    backend, port = backend_at_available_port()
    stop_sending = Event()
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.settimeout(0.2)

    def trickle_request() -> None:
        while not stop_sending.wait(0.02):
            try:
                client.sendall(b"x")
            except OSError:
                return

    sender = threading.Thread(target=trickle_request)
    try:
        client.sendall(b"G")
        sender.start()
        handler_threads = wait_for_handler_threads(backend)

        started = time.monotonic()
        backend.close()

        assert time.monotonic() - started < 1
        assert all(not thread.is_alive() for thread in handler_threads)
    finally:
        stop_sending.set()
        sender.join(timeout=1)
        client.close()
        backend.close()
    assert not sender.is_alive()


def test_close_does_not_deadlock_with_active_request_and_update(monkeypatch: pytest.MonkeyPatch) -> None:
    import refrain.display.image_server as image_server_module

    monkeypatch.setattr(image_server_module, "_REQUEST_LIFETIME", 0.1)
    backend, port = backend_at_available_port()
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.sendall(b"GET /display/current HTTP/1.1\r\n")
    handler_threads = wait_for_handler_threads(backend)

    entered_copy = Event()
    release_copy = Event()
    update_errors: list[Exception] = []
    image = Image.new("RGB", (4, 4), "yellow")
    original_copy = Image.Image.copy

    def blocked_copy(source: Image.Image) -> Image.Image:
        entered_copy.set()
        assert release_copy.wait(timeout=2)
        return original_copy(source)

    monkeypatch.setattr(Image.Image, "copy", blocked_copy)

    def update() -> None:
        try:
            backend.update(image)
        except DisplayBackendUpdateError as error:
            update_errors.append(error)

    updater = threading.Thread(target=update)
    updater.start()
    try:
        assert entered_copy.wait(timeout=2)
        started = time.monotonic()
        backend.close()
        assert time.monotonic() - started < 1
        assert all(not thread.is_alive() for thread in handler_threads)
    finally:
        release_copy.set()
        updater.join(timeout=2)
        client.close()
        image.close()
        backend.close()

    assert not updater.is_alive()
    assert len(update_errors) == 1
    assert "closed" in str(update_errors[0])


def test_occupied_port_is_reported_as_initialization_failure() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        with pytest.raises(DisplayBackendInitializationError, match="could not bind image-server"):
            ImageServerDisplayBackend(port=port)


def test_thread_start_failure_releases_bound_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    port = available_port()

    class FailedThread:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr("refrain.display.image_server.Thread", FailedThread)
    with pytest.raises(DisplayBackendInitializationError, match="thread unavailable"):
        ImageServerDisplayBackend(port=port)

    monkeypatch.undo()
    replacement = ImageServerDisplayBackend(port=port)
    replacement.close()

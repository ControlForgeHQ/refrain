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
    with pytest.raises(DisplayBackendUpdateError, match="closed"):
        backend.update(Image.new("RGB", (1, 1)))

    replacement = ImageServerDisplayBackend(port=port)
    replacement.close()


def test_close_does_not_wait_for_an_incomplete_client_request() -> None:
    backend, port = backend_at_available_port()
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.sendall(b"GET /display/current HTTP/1.1\r\n")
        time.sleep(0.05)

        started = time.monotonic()
        backend.close()

        assert time.monotonic() - started < 1


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

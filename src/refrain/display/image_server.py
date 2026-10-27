"""HTTP image-server display backend."""

from __future__ import annotations

import hashlib
import io
import logging
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from threading import Lock, Thread
from typing import ClassVar

from PIL import Image

from . import (
    DisplayBackendCloseError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
)

_LOGGER = logging.getLogger(__name__)
_CURRENT_IMAGE_PATH = "/display/current"
_REQUEST_TIMEOUT = 10


class _ImageHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with bounded handler lifetime and no reverse DNS lookup."""

    daemon_threads = True
    block_on_close = False

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        address_family: int,
    ) -> None:
        self.address_family = address_family
        super().__init__(server_address, request_handler_class, bind_and_activate=False)

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


class _ImageRequestHandler(BaseHTTPRequestHandler):
    """Serve only the currently accepted PNG representation."""

    backend: ClassVar[ImageServerDisplayBackend]
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        self.request.settimeout(_REQUEST_TIMEOUT)
        super().setup()

    def do_GET(self) -> None:
        if self.path != _CURRENT_IMAGE_PATH:
            self._send_status(404, b"Not found\n")
            return

        representation = self.backend._get_representation()
        if representation is None:
            self._send_status(503, b"Image not available\n")
            return

        image_bytes, entity_tag = representation
        if self._matches_entity_tag(entity_tag):
            self.send_response(304)
            self.send_header("ETag", entity_tag)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(image_bytes)))
        self.send_header("ETag", entity_tag)
        self.end_headers()
        try:
            self.wfile.write(image_bytes)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            _LOGGER.debug("image-server client disconnected while retrieving the current image")

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        del message, explain
        if code == 501:
            code = 405
        descriptions = {
            400: b"Bad request\n",
            403: b"Forbidden\n",
            404: b"Not found\n",
            405: b"Method not allowed\n",
            414: b"Request target too long\n",
            431: b"Request headers too large\n",
        }
        self._send_status(code, descriptions.get(code, b"Request failed\n"))

    def _send_status(self, status: int, body: bytes) -> None:
        try:
            self.send_response(status)
            if status == 405:
                self.send_header("Allow", "GET")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            _LOGGER.debug("image-server client disconnected before receiving an error response")

    def _matches_entity_tag(self, entity_tag: str) -> bool:
        for header_value in self.headers.get_all("If-None-Match", []):
            for candidate in header_value.split(","):
                candidate = candidate.strip()
                if candidate == "*":
                    return True
                if candidate.startswith("W/"):
                    candidate = candidate[2:].strip()
                if candidate == entity_tag:
                    return True
        return False

    def log_message(self, format_string: str, *args: object) -> None:
        _LOGGER.debug("image-server HTTP request: " + format_string, *args)


class ImageServerDisplayBackend:
    """Make complete Pillow images available at a read-only HTTP endpoint."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        if not isinstance(host, str) or not host:
            raise DisplayBackendInitializationError("image-server host must be a nonempty address or hostname")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise DisplayBackendInitializationError("image-server port must be an integer between 1 and 65535")

        self._state_lock = Lock()
        self._close_lock = Lock()
        self._closed = False
        self._representation: tuple[bytes, str] | None = None

        request_handler = type(
            "_BoundImageRequestHandler",
            (_ImageRequestHandler,),
            {"backend": self},
        )
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
        except OSError as error:
            raise DisplayBackendInitializationError(
                f"could not resolve image-server listening address {host!r}: {error}"
            ) from error

        server: _ImageHTTPServer | None = None
        bind_error: OSError | None = None
        for family, _socket_type, _protocol, _canonical_name, address in addresses:
            candidate: _ImageHTTPServer | None = None
            try:
                candidate = _ImageHTTPServer(address, request_handler, family)
                candidate.server_bind()
                candidate.server_activate()
            except OSError as error:
                if candidate is not None:
                    try:
                        candidate.server_close()
                    except OSError:
                        _LOGGER.exception("failed to release an unusable image-server listener")
                bind_error = error
                continue
            server = candidate
            break
        if server is None:
            raise DisplayBackendInitializationError(
                f"could not bind image-server to {host}:{port}: {bind_error or 'no usable listening address'}"
            ) from bind_error

        self._server = server
        self._thread = Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="refrain-image-server",
            daemon=True,
        )
        try:
            self._thread.start()
        except Exception as error:
            try:
                server.server_close()
            except OSError:
                _LOGGER.exception("failed to release image-server listener after thread startup failure")
            raise DisplayBackendInitializationError(f"could not start the image-server thread: {error}") from error

    def update(self, image: Image.Image) -> None:
        """Encode and publish a complete image without modifying caller-owned data."""
        if not isinstance(image, Image.Image):
            raise DisplayBackendUpdateError("image must be a Pillow Image.Image instance")
        with self._state_lock:
            if self._closed:
                raise DisplayBackendUpdateError("cannot update a closed image-server display")

        try:
            image_copy = image.copy()
            try:
                with io.BytesIO() as encoded_image:
                    image_copy.save(encoded_image, format="PNG")
                    image_bytes = encoded_image.getvalue()
            finally:
                image_copy.close()
            entity_tag = f'"{hashlib.sha256(image_bytes).hexdigest()}"'
        except Exception as error:
            raise DisplayBackendUpdateError(f"could not encode the image-server PNG representation: {error}") from error

        with self._state_lock:
            if self._closed:
                raise DisplayBackendUpdateError("cannot update a closed image-server display")
            self._representation = image_bytes, entity_tag

    def _get_representation(self) -> tuple[bytes, str] | None:
        with self._state_lock:
            return self._representation

    def close(self) -> None:
        """Stop the HTTP service and release its listening resources."""
        with self._close_lock:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True

            error: BaseException | None = None
            try:
                if self._thread.is_alive():
                    self._server.shutdown()
            except BaseException as close_error:
                error = close_error
            finally:
                try:
                    self._server.server_close()
                except BaseException as close_error:
                    error = error or close_error

            self._thread.join(timeout=5)
            if self._thread.is_alive():
                error = error or RuntimeError("the image-server thread did not stop")
            if error is not None:
                raise DisplayBackendCloseError(f"could not close the image-server: {error}") from error

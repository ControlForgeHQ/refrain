"""Independent, bounded HTTP access to verified filesystem publications."""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import ipaddress
import logging
import os
import re
import select
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Sequence

from .config import ApplicationConfigurationError
from .image_server_config import ImageServerConfiguration, load_image_server_config
from .publication_storage import PublicationDataset, PublicationStorageError

HANDLER_LIMIT = 4
VERIFICATION_LIMIT = 1
REQUESTS_PER_CONNECTION = 1
RECEPTION_TIMEOUT = 10.0
VERIFICATION_TIMEOUT = 60.0
RESPONSE_TIMEOUT = 120.0
WRITE_INACTIVITY_TIMEOUT = 15.0
SHUTDOWN_TIMEOUT = 5.0
_MAX_REQUEST_BYTES = 65536
_LOGGER = logging.getLogger(__name__)
_ENTITY_TAG = re.compile(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"')
_HOST_NAME = re.compile(r"(?:[A-Za-z0-9._~!$&'()*+;=-]|%[0-9A-Fa-f]{2})+\Z")
_OVERLOAD = (
    b"HTTP/1.1 503 Service Unavailable\r\n" b"Cache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
)


class _SocketWriter:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.deadline: float | None = None

    def write(self, data: bytes) -> int:
        if self.deadline is None:
            self.deadline = time.monotonic() + RESPONSE_TIMEOUT
        view = memoryview(data)
        total = len(view)
        while view:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("response deadline exceeded")
            self.connection.settimeout(min(remaining, WRITE_INACTIVITY_TIMEOUT))
            sent = self.connection.send(view)
            if not sent:
                raise ConnectionError("connection closed")
            view = view[sent:]
        return total

    def flush(self) -> None:
        pass


def _receive(connection: socket.socket) -> tuple[bytes, float]:
    deadline = time.monotonic() + RECEPTION_TIMEOUT
    data = bytearray()
    while b"\r\n\r\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline exceeded")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, _MAX_REQUEST_BYTES + 1 - len(data)))
        if not chunk:
            raise ConnectionError("connection closed")
        data.extend(chunk)
        if len(data) > _MAX_REQUEST_BYTES:
            raise ValueError("request too large")
    return bytes(data), deadline


def _matches_etag(header: str | None, tag: str) -> bool:
    if header is None:
        return False
    if header.strip() == "*":
        return True
    position = 0
    matched = False
    while position < len(header):
        while position < len(header) and header[position] in " \t,":
            position += 1
        if position == len(header):
            break
        match = _ENTITY_TAG.match(header, position)
        if match is None:
            return False
        candidate = match.group()
        matched |= candidate.removeprefix("W/") == tag
        position = match.end()
        while position < len(header) and header[position] in " \t":
            position += 1
        if position < len(header) and header[position] != ",":
            return False
    return matched


def _valid_host_header(value: str) -> bool:
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            return False
        try:
            ipaddress.IPv6Address(value[1:closing])
        except ValueError:
            return False
        suffix = value[closing + 1 :]
    else:
        host, separator, port = value.partition(":")
        if not _HOST_NAME.fullmatch(host):
            return False
        suffix = separator + port
    if not suffix:
        return True
    if not suffix.startswith(":") or not suffix[1:].isascii() or not suffix[1:].isdigit():
        return False
    port = suffix[1:].lstrip("0") or "0"
    return len(port) <= 5 and int(port) <= 65535


def _disconnected(connection: socket.socket) -> bool:
    try:
        if not select.select([connection], [], [], 0)[0]:
            return False
        timeout = connection.gettimeout()
        try:
            connection.setblocking(False)
            connection.recv(1, socket.MSG_PEEK)
            return False
        finally:
            connection.settimeout(timeout)
    except BlockingIOError:
        return False
    except (OSError, ValueError):
        return True


class ImageHTTPServer(ThreadingMixIn, HTTPServer):
    """A single listener with bounded, daemonized request and verification workers."""

    daemon_threads = True
    block_on_close = False
    allow_reuse_address = os.name != "nt"

    def __init__(self, address: tuple, family: int, config: ImageServerConfiguration) -> None:
        self.address_family = family
        self.config = config
        self.stopping = threading.Event()
        self.terminated = threading.Event()
        self.handlers = threading.BoundedSemaphore(HANDLER_LIMIT)
        self.verification = threading.BoundedSemaphore(VERIFICATION_LIMIT)
        self._condition = threading.Condition()
        self._clients: set[socket.socket] = set()
        self._failures: dict[str, tuple[str, bytes]] = {}
        super().__init__(address, ImageRequestHandler, bind_and_activate=False)
        try:
            self.server_bind()
            self.server_activate()
        except BaseException:
            self.server_close()
            raise

    def process_request(self, request: socket.socket, client_address: tuple) -> None:
        if self.stopping.is_set() or not self.handlers.acquire(blocking=False):
            _LOGGER.debug("Request capacity exhausted or service stopping")
            try:
                request.setblocking(False)
                request.send(_OVERLOAD)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        with self._condition:
            self._clients.add(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release(request)
            raise

    def _release(self, request: socket.socket) -> None:
        with self._condition:
            self._clients.discard(request)
            self._condition.notify_all()
        self.handlers.release()

    def process_request_thread(self, request: socket.socket, client_address: tuple) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release(request)

    def handle_error(self, request: socket.socket, client_address: tuple) -> None:
        _LOGGER.error("Unexpected image-server request failure")

    def _handle_request_noblock(self) -> None:
        try:
            request, client_address = self.get_request()
        except OSError as error:
            if error.errno in (errno.ECONNABORTED, errno.ECONNRESET, errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK):
                _LOGGER.debug("Incoming connection was interrupted")
                return
            raise
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except BaseException:
                self.shutdown_request(request)
                raise
        else:
            self.shutdown_request(request)

    def report_failure(self, destination: str, error: PublicationStorageError) -> None:
        message = str(error)
        missing = message.startswith(("publication destination does not exist:", "publication manifest is missing:"))
        kind = "missing" if missing else "invalid or inaccessible"
        cause = error.__cause__
        if missing:
            detail = "current publication is missing; wait for the publisher to create it"
        elif isinstance(cause, PermissionError):
            detail = "access denied; check the image-server account's publication read permissions"
        elif isinstance(cause, FileNotFoundError):
            detail = "a referenced publication file is missing; check the publisher and dataset"
        elif isinstance(cause, OSError):
            detail = "filesystem access failed; check publication storage and read permissions"
        elif message.startswith(("publication image hash", "publication metadata hash")):
            detail = "dataset checksum mismatch; check the publisher and dataset integrity"
        elif message.startswith(("publication manifest changed", "publication manifest changed while")):
            detail = "publication changed during verification; check the publisher if this persists"
        elif message.startswith(("manifest ", "unsupported publication manifest", "current publication manifest")):
            detail = "publication manifest is invalid; check the publisher and manifest"
        elif message.startswith(
            ("current publication metadata", "completed publication metadata", "publication metadata")
        ):
            detail = "publication metadata is invalid or inconsistent; check the publisher and dataset"
        elif message.startswith("published image"):
            detail = "publication image is invalid or inconsistent; check the publisher and dataset"
        elif message.startswith(("refusing to", "publication path", "publication destination is not")):
            detail = "publication path is unsafe or invalid; check the configured publication storage"
        else:
            detail = "verification failed; check publication storage, read permissions, and dataset integrity"
        fingerprint = hashlib.sha256(message.encode("utf-8", errors="replace")).digest()
        state = (kind, fingerprint)
        with self._condition:
            previous = self._failures.get(destination)
            if previous == state:
                return
            self._failures[destination] = state
        _LOGGER.log(
            logging.DEBUG if missing else logging.WARNING,
            "Publication %s for destination %s%s: %s",
            kind,
            destination,
            " (failure condition changed)" if previous is not None else "",
            detail,
        )

    def report_recovery(self, destination: str) -> None:
        with self._condition:
            previous = self._failures.pop(destination, None)
        if previous is not None:
            _LOGGER.info("Publication recovered for destination %s", destination)

    def verify(self, destination: str, connection: socket.socket) -> PublicationDataset | None:
        deadline = time.monotonic() + VERIFICATION_TIMEOUT
        while not self.stopping.is_set():
            if _disconnected(connection):
                _LOGGER.debug("Client disconnected while waiting for verification")
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOGGER.debug("Publication verification timed out")
                return None
            if self.verification.acquire(timeout=min(remaining, 0.1)):
                break
        else:
            return None
        if self.stopping.is_set() or time.monotonic() >= deadline:
            self.verification.release()
            if not self.stopping.is_set():
                _LOGGER.debug("Publication verification timed out")
            return None
        finished = threading.Event()
        result: list[PublicationDataset] = []

        def work() -> None:
            try:
                if self.stopping.is_set():
                    return
                if time.monotonic() >= deadline:
                    _LOGGER.debug("Publication verification timed out")
                    return
                dataset = self.config.read_current(
                    destination, cancelled=lambda: self.stopping.is_set() or time.monotonic() >= deadline
                )
                if time.monotonic() < deadline and not self.terminated.is_set():
                    self.report_recovery(destination)
                result.append(dataset)
            except PublicationStorageError as error:
                if not self.stopping.is_set() and time.monotonic() < deadline:
                    self.report_failure(destination, error)
                else:
                    _LOGGER.debug("Publication verification cancelled or timed out")
            except Exception:
                _LOGGER.error("Unexpected publication verification failure for destination %s", destination)
            finally:
                self.verification.release()
                finished.set()

        try:
            threading.Thread(target=work, daemon=True, name="image-verification").start()
        except Exception:
            self.verification.release()
            _LOGGER.error("Cannot start publication verification worker")
            return None
        while True:
            if _disconnected(connection):
                _LOGGER.debug("Client disconnected during verification")
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOGGER.debug("Publication verification timed out")
                return None
            if self.terminated.is_set():
                return None
            if finished.wait(min(remaining, 0.1)):
                if time.monotonic() >= deadline:
                    _LOGGER.debug("Publication verification timed out")
                    return None
                if self.terminated.is_set():
                    return None
                return result[0] if result else None

    def stop(self) -> None:
        self.stopping.set()
        self.server_close()
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        with self._condition:
            while self._clients:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            clients = tuple(self._clients)
        self.terminated.set()
        for connection in clients:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()


class ImageRequestHandler(BaseHTTPRequestHandler):
    server: ImageHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "Refrain"
    sys_version = ""

    def setup(self) -> None:
        self.connection = self.request

    def finish(self) -> None:
        pass

    def handle(self) -> None:
        self.close_connection = True
        try:
            request, self.receive_deadline = _receive(self.connection)
            self.rfile = io.BytesIO(request)
            self.wfile = _SocketWriter(self.connection)
            self.handle_one_request()
        except (OSError, TimeoutError, ConnectionError):
            _LOGGER.debug("Client disconnected or request timed out")
        except ValueError:
            _LOGGER.debug("Oversized request")
        except Exception:
            _LOGGER.error("Unexpected image-server request failure")

    def handle_one_request(self) -> None:
        self.raw_requestline = self.rfile.readline(65537)
        if not self.parse_request():
            return
        if self.headers.defects:
            self._respond(400)
            return
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.0"
            self._respond(400)
            return
        hosts = self.headers.get_all("Host", [])
        if self.request_version != "HTTP/1.0" and (len(hosts) != 1 or not _valid_host_header(hosts[0])):
            self._respond(400)
            return
        if self.command not in ("GET", "HEAD"):
            self._respond(405, extra={"Allow": "GET, HEAD"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        encodings = self.headers.get_all("Transfer-Encoding", [])
        if encodings and lengths:
            self._respond(400)
            return
        if encodings:
            self._respond(501)
            return
        if lengths and (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()):
            self._respond(400)
            return
        length_text = lengths[0].lstrip("0") or "0" if lengths else "0"
        if len(length_text) > 5 or int(length_text) > _MAX_REQUEST_BYTES:
            self._respond(413)
            return
        if lengths:
            remaining = int(length_text)
            remaining -= len(self.rfile.read(remaining))
            while remaining:
                allowance = self.receive_deadline - time.monotonic()
                if allowance <= 0:
                    raise TimeoutError("request deadline exceeded")
                self.connection.settimeout(allowance)
                chunk = self.connection.recv(min(remaining, 4096))
                if not chunk:
                    raise ConnectionError("incomplete request body")
                remaining -= len(chunk)
        parts = self.path.split("/")
        if (
            len(parts) != 4
            or self.requestline.split()[1] != self.path
            or parts[1] != "destination"
            or parts[3] != "current"
            or parts[2] not in self.server.config.destinations
        ):
            self._respond(404)
            return
        dataset = self.server.verify(parts[2], self.connection)
        if dataset is None:
            self._respond(503)
            return
        tag = f'"{dataset.manifest.image_sha256}"'
        values = self.headers.get_all("If-None-Match", [])
        if _matches_etag(",".join(values) if values else None, tag):
            self._respond(304, extra={"ETag": tag, "Cache-Control": "no-cache"})
        else:
            self._respond(
                200,
                dataset.image,
                {"Content-Type": "image/png", "ETag": tag, "Cache-Control": "no-cache"},
            )

    def handle_expect_100(self) -> bool:
        self._respond(417)
        return False

    def _respond(self, status: int, body: bytes = b"", extra: dict[str, str] | None = None) -> None:
        if self.server.terminated.is_set():
            return
        self.send_response(status)
        headers = extra or {}
        if status >= 400:
            headers["Cache-Control"] = "no-store"
        if status != 304:
            headers["Content-Length"] = str(len(body))
        headers["Connection"] = "close"
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)
        _LOGGER.debug("HTTP request completed with status %d", status)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.0"
        self._respond(code)

    def log_message(self, format: str, *args: object) -> None:
        pass


def create_server(config: ImageServerConfiguration) -> ImageHTTPServer:
    """Resolve and bind exactly one listener, trying addresses in resolver order."""
    last_error: OSError | None = None
    for family, socktype, protocol, _, address in socket.getaddrinfo(config.host, config.port, type=socket.SOCK_STREAM):
        try:
            return ImageHTTPServer(address, family, config)
        except OSError as error:
            last_error = error
    raise OSError("no resolved address could be bound") from last_error


def run(server: ImageHTTPServer) -> None:
    """Run the foreground listener until shutdown is requested."""
    server.timeout = 0.2
    _LOGGER.info("Listening on %s; destinations: %s", server.server_address, ", ".join(server.config.destinations))
    try:
        while not server.stopping.is_set():
            server.handle_request()
    finally:
        server.stop()
        _LOGGER.info("Image server stopped")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="refrain-image-server")
    parser.add_argument("--config")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        config = load_image_server_config(args.config)
    except ApplicationConfigurationError:
        return 78
    except Exception:
        _LOGGER.error("Cannot load image-server configuration; check the selected configuration")
        return 78
    try:
        server = create_server(config)
    except OSError as error:
        _LOGGER.error("Cannot initialize image-server listener; check host and port: %s", error)
        return 1
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda _signum, _frame: server.stopping.set())
        run(server)
    except Exception:
        _LOGGER.error("Image-server listener failed; check the service environment")
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

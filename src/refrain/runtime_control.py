"""Authenticated, local-only transport for resident publication control."""

from __future__ import annotations

import ctypes
import hmac
import io
import json
import logging
import os
import re
import secrets
import socket
import stat
import struct
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path
from threading import BoundedSemaphore, Event, Lock, Thread

from PIL import Image, UnidentifiedImageError

from .display.coordinator import (
    DisplayPublicationCoordinator,
    PublicationOperation,
    PublicationResult,
    PublicationStatus,
)
from .geometry import PresentationGeometryError, ResolvedOutputSpecification

_LOG = logging.getLogger(__name__)
_VERSION = 1
_MAX_METADATA = 65536
_MAX_IMAGE_BYTES = 32 * 1024 * 1024
_MAX_TOTAL_BYTES = 40 * 1024 * 1024
_MAX_DESTINATIONS = 64
_MAX_IMAGES = 2
_MAX_WIDTH = 3840
_MAX_HEIGHT = 2400
_MAX_PIXELS = 9_216_000
_MAX_TOTAL_PIXELS = 12_000_000
_IDENTIFIER_CHUNK = 4096
_MAX_ERROR_CHARS = 1024
_MAX_CONNECTIONS = 2
_AUTH_TIMEOUT = 3.0
_IO_TIMEOUT = 10.0
_MAX_REQUEST_TIME = 60.0


class RuntimeControlError(Exception):
    """Base class for application-facing control errors."""


class RuntimeUnavailable(RuntimeControlError):
    """The resident endpoint is unavailable."""


class RuntimeAuthenticationError(RuntimeControlError):
    """The runtime rejected the credential."""


class RuntimeProtocolError(RuntimeControlError):
    """The peer or request did not satisfy the control protocol."""


class RuntimeUnsupportedProtocol(RuntimeProtocolError):
    """The runtime does not support the requested protocol version."""


class RuntimeUnconfirmed(RuntimeControlError):
    """A submitted publication may have completed but its result was lost."""


class RuntimeAdmissionRejected(RuntimeControlError):
    """An admission guard rejected the request and released its images."""


class _TransientUnsupported(RuntimeControlError):
    pass


AdmissionGuard = Callable[[tuple[int, int], Mapping[ResolvedOutputSpecification, Image.Image]], PublicationOperation]
TransientAdmissionGuard = Callable[
    [
        Iterable[str] | str,
        Mapping[str, ResolvedOutputSpecification],
        Mapping[ResolvedOutputSpecification, Image.Image],
    ],
    PublicationOperation,
]
TransientAdmission = Callable[
    [
        Iterable[str] | str,
        Mapping[str, ResolvedOutputSpecification],
        Mapping[ResolvedOutputSpecification, Image.Image],
        TransientAdmissionGuard,
    ],
    PublicationOperation,
]


def _encode(value: object) -> bytes:
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(data) > _MAX_METADATA:
        raise RuntimeProtocolError("control metadata exceeds the size limit")
    return data


def _decode(data: bytes) -> dict:
    if len(data) > _MAX_METADATA:
        raise RuntimeProtocolError("control metadata exceeds the size limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise RuntimeProtocolError("invalid control metadata") from error
    if not isinstance(value, dict):
        raise RuntimeProtocolError("control metadata must be an object")
    return value


def _spec_to_wire(specification: ResolvedOutputSpecification) -> dict:
    return {"aspect_ratio": specification.aspect_ratio, "size": list(specification.requested_output_size)}


def _spec_from_wire(value: object) -> ResolvedOutputSpecification:
    if not isinstance(value, dict) or set(value) != {"aspect_ratio", "size"}:
        raise RuntimeProtocolError("invalid output specification")
    size = value["size"]
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
        raise RuntimeProtocolError("invalid output dimensions")
    try:
        return ResolvedOutputSpecification(value["aspect_ratio"], tuple(size))
    except (PresentationGeometryError, TypeError) as error:
        raise RuntimeProtocolError("invalid output specification") from error


def _supports_transient_spec(specification: ResolvedOutputSpecification) -> bool:
    width, height = specification.requested_output_size
    return width <= _MAX_WIDTH and height <= _MAX_HEIGHT and width * height <= _MAX_PIXELS


def _send(connection: Connection, value: object) -> None:
    connection.send_bytes(_encode(value))


def _set_socket_timeouts(connection: Connection, seconds: int = int(_IO_TIMEOUT)) -> None:
    if os.name != "nt":
        with socket.fromfd(connection.fileno(), socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            timeout = struct.pack("@ll", seconds, 0)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, timeout)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, timeout)


def _receive(
    connection: Connection,
    stop: Event | None = None,
    deadline: float | None = None,
    *,
    wait_timeout: float | None = None,
) -> bytes:
    timeout = _IO_TIMEOUT if wait_timeout is None else wait_timeout
    end = min(time.monotonic() + timeout, deadline or float("inf"))
    while not connection.poll(min(0.1, max(0.0, end - time.monotonic()))):
        if stop is not None and stop.is_set():
            raise RuntimeProtocolError("runtime is stopping")
        if time.monotonic() >= end:
            raise RuntimeProtocolError("control request timed out")
    return connection.recv_bytes(_MAX_METADATA)


def _ensure_connected(connection: Connection) -> None:
    if connection.poll(0):
        # A request has no messages after commit; EOF or extra input forbids admission.
        raise RuntimeProtocolError("unexpected data after request")


class _RequestDeadline:
    """Interrupt incomplete I/O without depending on a peer's message framing."""

    def __init__(self, connection: Connection, *, timeout: float = _MAX_REQUEST_TIME) -> None:
        self._connection = connection
        self._lock = Lock()
        self._finished = Event()
        self._aborted = Event()
        self._authenticated = Event()
        self._deadline = time.monotonic() + timeout
        self._thread = Thread(target=self._watch, name="refrain-control-deadline", daemon=True)
        self._thread.start()

    def authenticated(self) -> None:
        self._authenticated.set()

    def progress(self, timeout: float = _MAX_REQUEST_TIME) -> None:
        with self._lock:
            self._deadline = time.monotonic() + timeout

    def is_set(self) -> bool:
        return self._aborted.is_set()

    def finish(self) -> None:
        with self._lock:
            self._finished.set()
            self._authenticated.set()

    def abort(self, *, expired_only: bool = False) -> None:
        with self._lock:
            if self._finished.is_set() or (expired_only and time.monotonic() < self._deadline):
                return
            self._aborted.set()
            try:
                if os.name == "nt":
                    from ctypes import wintypes

                    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                    cancel = kernel.CancelIoEx
                    cancel.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
                    cancel.restype = wintypes.BOOL
                    cancel(self._connection.fileno(), None)
                else:
                    with socket.fromfd(self._connection.fileno(), socket.AF_UNIX, socket.SOCK_STREAM) as peer:
                        peer.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass

    def _watch(self) -> None:
        if not self._authenticated.wait(_AUTH_TIMEOUT):
            while not self._finished.is_set():
                self.abort()
                self._finished.wait(0.1)
            return
        while not self._finished.is_set():
            with self._lock:
                remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                self.abort(expired_only=True)
                self._finished.wait(0.1)
            else:
                self._finished.wait(min(remaining, 0.1))


def _validated_address(metadata_path: Path, family: str, address: object) -> str:
    if not isinstance(address, str):
        raise RuntimeProtocolError("invalid runtime endpoint")
    if family == "AF_PIPE":
        valid = re.fullmatch(r"\\\\\.\\pipe\\refrain-[0-9a-f]{32}", address) is not None
    elif address.startswith("\0"):
        valid = sys.platform.startswith("linux") and re.fullmatch("\0refrain-[0-9a-f]{32}", address) is not None
    else:
        path = Path(address)
        valid = (
            path.parent == metadata_path.parent and re.fullmatch(r"refrain-[0-9a-f]{16}\.sock", path.name) is not None
        )
    if not valid:
        raise RuntimeProtocolError("invalid runtime endpoint")
    if family == "AF_UNIX" and not address.startswith("\0"):
        details = os.lstat(address)
        if not stat.S_ISSOCK(details.st_mode) or details.st_uid != os.geteuid():
            raise RuntimeProtocolError("invalid runtime socket")
    return address


def _validate_metadata_directory(path: Path) -> None:
    if os.name == "nt":
        return
    details = path.lstat()
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid() or details.st_mode & 0o022:
        raise RuntimeProtocolError("runtime metadata directory must be owned and not writable by others")


def _wake_listener(address: str) -> None:
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        handle = create(address, 0xC0000000, 0, None, 3, 0x40000000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
    else:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as wake:
            wake.settimeout(0.2)
            wake.connect(address)


def _private_file(path: Path, data: bytes) -> None:
    """Create metadata atomically with a private DACL on Windows or mode 0600 on Unix."""
    temporary = path.with_name(path.name + "." + secrets.token_hex(8))
    fd = None
    try:
        if os.name == "nt":
            import msvcrt
            from ctypes import wintypes

            class SecurityAttributes(ctypes.Structure):
                _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]

            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
            convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            convert.restype = wintypes.BOOL
            create = kernel.CreateFileW
            create.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(SecurityAttributes),
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create.restype = wintypes.HANDLE
            descriptor = ctypes.c_void_p()
            if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
                handle = create(str(temporary), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
                except BaseException:
                    kernel.CloseHandle(handle)
                    raise
            finally:
                kernel.LocalFree.argtypes = [ctypes.c_void_p]
                kernel.LocalFree(descriptor)
        else:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as file:
            fd = None
            file.write(data)
        os.replace(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _bounded_outcome(outcome: tuple[bool | None, str | None]) -> tuple[bool | None, str | None]:
    success, error = outcome
    if error is not None and len(error) > _MAX_ERROR_CHARS:
        suffix = " [truncated]"
        error = error[: _MAX_ERROR_CHARS - len(suffix)] + suffix
    return success, error


def _result_wire(result: PublicationResult) -> dict:
    return {
        "version": _VERSION,
        "status": result.status.value,
        "destinations": {key: _bounded_outcome(value) for key, value in result.destinations.items()},
    }


def _result_from_wire(value: dict) -> PublicationResult:
    try:
        if value.get("version") != _VERSION:
            raise RuntimeUnsupportedProtocol("unsupported runtime-control protocol")
        status = PublicationStatus(value["status"])
        outcomes = value["destinations"]
        if not isinstance(outcomes, dict) or len(outcomes) > _MAX_DESTINATIONS:
            raise ValueError("invalid destinations")
        for key, pair in outcomes.items():
            if (
                not isinstance(key, str)
                or not isinstance(pair, list)
                or len(pair) != 2
                or (pair[0] is not None and type(pair[0]) is not bool)
                or (pair[1] is not None and not isinstance(pair[1], str))
            ):
                raise ValueError("invalid outcome")
        return PublicationResult(status, {key: tuple(pair) for key, pair in outcomes.items()})
    except (KeyError, ValueError, TypeError) as error:
        raise RuntimeProtocolError("invalid publication response") from error


def _receive_result(
    connection: Connection, *, terminal: bool = False, initial_response: dict | None = None
) -> PublicationResult:
    def receive() -> dict:
        data = (
            connection.recv_bytes(_MAX_METADATA) if terminal else _receive(connection, wait_timeout=_MAX_REQUEST_TIME)
        )
        return _decode(data)

    response = receive() if initial_response is None else initial_response
    if response.get("status") != "result-stream":
        if response.get("status") == "unsupported-protocol":
            raise RuntimeUnsupportedProtocol("unsupported runtime-control protocol")
        if response.get("status") == "invalid" and "destinations" not in response:
            raise RuntimeProtocolError(response.get("message", "invalid request"))
        return _result_from_wire(response)
    if set(response) != {"version", "status", "result_status"} or response["version"] != _VERSION:
        raise RuntimeProtocolError("invalid publication response")
    try:
        status = PublicationStatus(response["result_status"])
    except (ValueError, TypeError) as error:
        raise RuntimeProtocolError("invalid publication response") from error
    outcomes = {}
    while True:
        record = receive()
        if record == {"version": _VERSION, "status": "result-end"}:
            return PublicationResult(status, outcomes)
        if (
            set(record) != {"version", "status", "identifier", "outcome"}
            or record["version"] != _VERSION
            or record["status"] not in ("result-destination", "result-destination-start")
        ):
            raise RuntimeProtocolError("invalid publication response")
        identifier = record["identifier"]
        if record["status"] == "result-destination-start":
            if identifier != "":
                raise RuntimeProtocolError("invalid publication response")
            parts = []
            while True:
                part = receive()
                if part == {"version": _VERSION, "status": "destination-end"}:
                    break
                if (
                    set(part) != {"version", "status", "value"}
                    or part["version"] != _VERSION
                    or part["status"] != "identifier-part"
                    or not isinstance(part["value"], str)
                    or not 1 <= len(part["value"]) <= _IDENTIFIER_CHUNK
                ):
                    raise RuntimeProtocolError("invalid publication response")
                parts.append(part["value"])
            if not parts:
                raise RuntimeProtocolError("invalid publication response")
            identifier = "".join(parts)
        if not isinstance(identifier, str) or identifier in outcomes:
            raise RuntimeProtocolError("invalid publication response")
        part = _result_from_wire(
            {"version": _VERSION, "status": status.value, "destinations": {identifier: record["outcome"]}}
        )
        outcomes[identifier] = part.destinations[identifier]


class _BoundedImageBuffer(io.BytesIO):
    def write(self, data: bytes) -> int:
        if self.tell() + len(data) > _MAX_IMAGE_BYTES:
            raise RuntimeProtocolError("image exceeds transport limit")
        return super().write(data)


class RuntimeControlServer:
    """Resident listener. The caller must hold installation ownership until close."""

    def __init__(
        self,
        coordinator: DisplayPublicationCoordinator,
        metadata_path: Path,
        refresh: Callable[[AdmissionGuard], PublicationOperation],
        *,
        shutdown_event: Event | None = None,
        transient_admission: TransientAdmission | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._metadata_path = Path(metadata_path)
        self._refresh = refresh
        self._transient_admission = transient_admission
        self._shutdown_event = shutdown_event if shutdown_event is not None else Event()
        self._credential = secrets.token_hex(32)
        self._stop = Event()
        self._slots = BoundedSemaphore(_MAX_CONNECTIONS)
        self._lock = Lock()
        self._handlers: set[Thread] = set()
        self._deadlines: set[_RequestDeadline] = set()
        self._listener: Listener | None = None
        self._thread: Thread | None = None
        self._address: str | None = None
        self._metadata: bytes | None = None

    def start(self) -> None:
        if self._listener is not None or self._stop.is_set():
            raise RuntimeControlError("runtime-control listener already started or stopped")
        family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        address = (
            rf"\\.\pipe\refrain-{secrets.token_hex(16)}"
            if os.name == "nt"
            else str(self._metadata_path.parent / ("refrain-" + secrets.token_hex(8) + ".sock"))
        )
        if sys.platform.startswith("linux") and len(os.fsencode(address)) >= 104:
            address = "\0refrain-" + secrets.token_hex(16)
        self._address = address
        try:
            self._metadata_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _validate_metadata_directory(self._metadata_path.parent)
            self._listener = Listener(address, family=family)
            if os.name != "nt":
                if not address.startswith("\0"):
                    os.chmod(address, 0o600)
                self._remove_stale_socket()
            self._metadata = _encode(
                {"version": _VERSION, "family": family, "address": address, "credential": self._credential}
            )
            _private_file(self._metadata_path, self._metadata)
            self._thread = Thread(target=self._serve, name="refrain-control-listener", daemon=True)
            self._thread.start()
        except (OSError, RuntimeError, ValueError) as error:
            self.close()
            raise RuntimeControlError(f"cannot start runtime-control listener: {error}") from error
        except BaseException:
            self.close()
            raise

    def _remove_stale_socket(self) -> None:
        try:
            with self._metadata_path.open("rb") as file:
                old = _decode(file.read(_MAX_METADATA + 1))
            address = old.get("address")
            if old.get("family") != "AF_UNIX" or not isinstance(address, str):
                return
            path = Path(address)
            if (
                path.parent == self._metadata_path.parent
                and re.fullmatch(r"refrain-[0-9a-f]{16}\.sock", path.name) is not None
                and stat.S_ISSOCK(path.lstat().st_mode)
                and path.lstat().st_uid == os.geteuid()
            ):
                path.unlink()
        except (OSError, ValueError, RuntimeProtocolError):
            pass

    def _serve(self) -> None:
        listener = self._listener
        assert listener is not None
        while not self._stop.is_set():
            try:
                connection = listener.accept()
            except (OSError, EOFError, RuntimeProtocolError):
                if not self._stop.is_set():
                    _LOG.exception("Runtime-control listener failed")
                return
            if self._stop.is_set() or not self._slots.acquire(blocking=False):
                connection.close()
                continue
            try:
                _set_socket_timeouts(connection)
            except OSError:
                connection.close()
                self._slots.release()
                continue
            thread = Thread(target=self._handle, args=(connection,), name="refrain-control-request", daemon=True)
            try:
                with self._lock:
                    if self._stop.is_set():
                        connection.close()
                        self._slots.release()
                        continue
                    self._handlers.add(thread)
                    thread.start()
            except RuntimeError:
                with self._lock:
                    self._handlers.discard(thread)
                self._slots.release()
                connection.close()
                _LOG.exception("Cannot start runtime-control request handler")

    def _handle(self, connection: Connection) -> None:
        from threading import current_thread

        images: dict[ResolvedOutputSpecification, Image.Image] = {}
        deadline = time.monotonic() + _MAX_REQUEST_TIME
        guard = None
        try:
            guard = _RequestDeadline(connection)
            with self._lock:
                self._deadlines.add(guard)
                if self._stop.is_set():
                    return
            auth = _decode(_receive(connection, guard, deadline))
            credential = auth.get("credential")
            if (
                set(auth) != {"credential"}
                or not isinstance(credential, str)
                or not hmac.compare_digest(credential, self._credential)
            ):
                _send(connection, {"version": _VERSION, "status": "authentication-failed"})
                return
            guard.authenticated()
            _send(connection, {"version": _VERSION, "status": "authenticated"})
            request = _decode(_receive(connection, guard, deadline))
            if self._stop.is_set() or guard.is_set():
                raise RuntimeAdmissionRejected("runtime is stopping or request expired")
            if type(request.get("version")) is not int or request["version"] != _VERSION:
                _send(connection, {"version": _VERSION, "status": "unsupported-protocol"})
                return
            operation = request.get("operation")
            if operation == "discover" and set(request) == {"version", "operation"}:

                def send_discovery(message):
                    _send(connection, message)
                    guard.progress()

                for record in self._coordinator.iter_destination_statuses():
                    specification = record["output_specification"]
                    identifier = record["identifier"]
                    wire_record = {
                        **record,
                        "supports_transient": record["supports_transient"] and _supports_transient_spec(specification),
                        "output_specification": _spec_to_wire(specification),
                    }
                    if len(identifier) > _IDENTIFIER_CHUNK:
                        wire_record["identifier"] = ""
                        send_discovery({"version": _VERSION, "status": "destination-start", "destination": wire_record})
                        for offset in range(0, len(identifier), _IDENTIFIER_CHUNK):
                            send_discovery(
                                {
                                    "version": _VERSION,
                                    "status": "identifier-part",
                                    "value": identifier[offset : offset + _IDENTIFIER_CHUNK],
                                },
                            )
                        send_discovery({"version": _VERSION, "status": "destination-end"})
                        continue
                    send_discovery({"version": _VERSION, "status": "destination", "destination": wire_record})
                send_discovery({"version": _VERSION, "status": "succeeded"})
                return
            if operation == "refresh" and set(request) == {"version", "operation"}:
                if self._stop.is_set() or self._shutdown_event.is_set() or guard.is_set():
                    raise RuntimeAdmissionRejected("runtime is stopping or request expired")
                _ensure_connected(connection)

                def admit_refresh(
                    identity: tuple[int, int], images: Mapping[ResolvedOutputSpecification, Image.Image]
                ) -> PublicationOperation:
                    with self._lock:
                        if self._stop.is_set() or self._shutdown_event.is_set() or guard.is_set():
                            DisplayPublicationCoordinator._close_images(images)
                            raise RuntimeAdmissionRejected("runtime is stopping or request expired")
                        try:
                            _ensure_connected(connection)
                        except (OSError, EOFError, RuntimeProtocolError) as error:
                            DisplayPublicationCoordinator._close_images(images)
                            raise RuntimeAdmissionRejected("control client disconnected before admission") from error
                        return self._coordinator.force_scheduled_publication(identity, images)

                publication = self._refresh(admit_refresh)
            elif operation == "publish":
                target, specifications, images = self._read_publication(connection, request, deadline, guard)
                if self._stop.is_set() or self._shutdown_event.is_set() or guard.is_set():
                    raise RuntimeAdmissionRejected("runtime is stopping or request expired")
                _ensure_connected(connection)

                def admit_transient(
                    selected: Iterable[str] | str,
                    output_specifications: Mapping[str, ResolvedOutputSpecification],
                    supplied_images: Mapping[ResolvedOutputSpecification, Image.Image],
                ) -> PublicationOperation:
                    with self._lock:
                        if self._stop.is_set() or self._shutdown_event.is_set() or guard.is_set():
                            DisplayPublicationCoordinator._close_images(supplied_images)
                            raise RuntimeAdmissionRejected("runtime is stopping or request expired")
                        try:
                            _ensure_connected(connection)
                        except (OSError, EOFError, RuntimeProtocolError) as error:
                            DisplayPublicationCoordinator._close_images(supplied_images)
                            raise RuntimeAdmissionRejected("control client disconnected before admission") from error
                        return self._coordinator.publish_transient(selected, output_specifications, supplied_images)

                transferred_images, images = images, {}
                if self._transient_admission is None:
                    publication = admit_transient(target, specifications, transferred_images)
                else:
                    publication = self._transient_admission(target, specifications, transferred_images, admit_transient)
            else:
                raise RuntimeProtocolError("invalid control operation")
            guard.finish()
            initial = publication.result
            if initial.status is PublicationStatus.ACCEPTED:
                try:
                    self._send_publication_response(connection, initial)
                    can_respond = True
                except (OSError, EOFError, RuntimeProtocolError):
                    can_respond = False
                # The coordinator owns admitted work even when this connection closes.
                while True:
                    result = publication.wait(0.1)
                    if result.status is not PublicationStatus.ACCEPTED:
                        if can_respond:
                            self._send_publication_response(connection, result)
                        return
            else:
                self._send_publication_response(connection, initial)
        except _TransientUnsupported:
            try:
                _send(connection, _result_wire(PublicationResult(PublicationStatus.UNSUPPORTED, {})))
            except (OSError, EOFError, RuntimeProtocolError):
                pass
        except RuntimeAdmissionRejected:
            try:
                _send(connection, _result_wire(PublicationResult(PublicationStatus.STOPPING, {})))
            except (OSError, EOFError, RuntimeProtocolError):
                pass
        except (
            RuntimeProtocolError,
            OSError,
            EOFError,
            ValueError,
            TypeError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ) as error:
            try:
                _send(connection, {"version": _VERSION, "status": "invalid", "message": str(error)[:512]})
            except (OSError, EOFError, RuntimeProtocolError):
                pass
        except Exception:
            _LOG.exception("Runtime-control request failed")
            try:
                _send(connection, {"version": _VERSION, "status": "failed", "destinations": {}})
            except (OSError, EOFError, RuntimeProtocolError):
                pass
        finally:
            if guard is not None:
                guard.finish()
                with self._lock:
                    self._deadlines.discard(guard)
            for image in images.values():
                image.close()
            connection.close()
            with self._lock:
                self._handlers.discard(current_thread())
            self._slots.release()

    @staticmethod
    def _send_publication_response(connection: Connection, result: PublicationResult) -> None:
        deadline = _RequestDeadline(connection, timeout=_IO_TIMEOUT)
        deadline.authenticated()
        try:
            if deadline.is_set():
                raise RuntimeProtocolError("control response timed out")
            estimated_size = sum(
                len(key) * 12 + (min(len(value[1]), _MAX_ERROR_CHARS) * 12 if value[1] else 0) + 32
                for key, value in result.destinations.items()
            )
            if len(result.destinations) <= _MAX_DESTINATIONS and estimated_size < _MAX_METADATA - 128:
                _send(connection, _result_wire(result))
            else:
                _send(
                    connection, {"version": _VERSION, "status": "result-stream", "result_status": result.status.value}
                )
                deadline.progress(_IO_TIMEOUT)
                for identifier, outcome in result.destinations.items():
                    long_identifier = len(identifier) > _IDENTIFIER_CHUNK
                    _send(
                        connection,
                        {
                            "version": _VERSION,
                            "status": "result-destination-start" if long_identifier else "result-destination",
                            "identifier": "" if long_identifier else identifier,
                            "outcome": _bounded_outcome(outcome),
                        },
                    )
                    deadline.progress(_IO_TIMEOUT)
                    if long_identifier:
                        for offset in range(0, len(identifier), _IDENTIFIER_CHUNK):
                            _send(
                                connection,
                                {
                                    "version": _VERSION,
                                    "status": "identifier-part",
                                    "value": identifier[offset : offset + _IDENTIFIER_CHUNK],
                                },
                            )
                            deadline.progress(_IO_TIMEOUT)
                        _send(connection, {"version": _VERSION, "status": "destination-end"})
                        deadline.progress(_IO_TIMEOUT)
                _send(connection, {"version": _VERSION, "status": "result-end"})
        finally:
            deadline.finish()

    def _read_publication(self, connection: Connection, request: dict, deadline: float, guard: _RequestDeadline):
        fields = {"version", "operation", "target", "specifications", "images"}
        preflight = request.get("preflight", False)
        if set(request) not in (fields, fields | {"preflight"}) or ("preflight" in request and preflight is not True):
            raise RuntimeProtocolError("invalid publication request")
        target = request["target"]
        if target != "all" and (
            not isinstance(target, list)
            or not 1 <= len(target) <= _MAX_DESTINATIONS
            or any(not isinstance(item, str) or not item or len(item) > 256 for item in target)
            or len(set(target)) != len(target)
        ):
            raise RuntimeProtocolError("invalid target")
        specifications = request["specifications"]
        if (
            not isinstance(specifications, dict)
            or len(specifications) > _MAX_DESTINATIONS
            or any(not isinstance(k, str) or not k or len(k) > 256 for k in specifications)
        ):
            raise RuntimeProtocolError("invalid destination specifications")
        specifications = {key: _spec_from_wire(value) for key, value in specifications.items()}
        selected = None if target == "all" else set(target)
        if any(
            (selected is None and record["participating"] or selected is not None and record["identifier"] in selected)
            and not _supports_transient_spec(record["output_specification"])
            for record in self._coordinator.iter_destination_statuses()
        ) or any(not _supports_transient_spec(spec) for spec in specifications.values()):
            raise _TransientUnsupported()
        descriptors = request["images"]
        if not isinstance(descriptors, list) or not 1 <= len(descriptors) <= _MAX_IMAGES:
            raise RuntimeProtocolError("invalid image count")
        parsed = []
        total_bytes = total_pixels = 0
        for descriptor in descriptors:
            if not isinstance(descriptor, dict) or set(descriptor) != {"specification", "encoding", "length"}:
                raise RuntimeProtocolError("invalid image descriptor")
            spec = _spec_from_wire(descriptor["specification"])
            if not _supports_transient_spec(spec):
                raise _TransientUnsupported()
            length = descriptor["length"]
            if descriptor["encoding"] != "png" or type(length) is not int or not 0 < length <= _MAX_IMAGE_BYTES:
                raise RuntimeProtocolError("invalid image encoding or size")
            if spec in [item[0] for item in parsed]:
                raise RuntimeProtocolError("duplicate image specification")
            total_bytes += length
            total_pixels += spec.requested_output_size[0] * spec.requested_output_size[1]
            parsed.append((spec, length))
        if total_bytes > _MAX_TOTAL_BYTES or total_pixels > _MAX_TOTAL_PIXELS:
            raise RuntimeProtocolError("publication exceeds resource limits")
        if set(specifications.values()) != {spec for spec, _ in parsed}:
            raise RuntimeProtocolError("inconsistent image specifications")
        if target != "all" and set(target) != set(specifications):
            raise RuntimeProtocolError("inconsistent destinations")
        if preflight:
            _send(connection, {"version": _VERSION, "status": "ready"})
        images = {}
        try:
            for spec, length in parsed:
                end = min(time.monotonic() + _IO_TIMEOUT, deadline)
                while not connection.poll(max(0, min(0.1, end - time.monotonic()))):
                    if guard.is_set() or time.monotonic() >= end:
                        raise RuntimeProtocolError("image transfer timed out")
                data = connection.recv_bytes(length)
                if len(data) != length:
                    raise RuntimeProtocolError("incomplete image payload")
                with Image.open(io.BytesIO(data), formats=["PNG"]) as source:
                    if (
                        source.format != "PNG"
                        or getattr(source, "n_frames", 1) != 1
                        or source.size != spec.requested_output_size
                        or source.mode != "RGB"
                    ):
                        raise RuntimeProtocolError("image must be a single-frame RGB PNG matching the specification")
                    source.load()
                    images[spec] = source.copy()
            if _decode(_receive(connection, guard, deadline)) != {"commit": True}:
                raise RuntimeProtocolError("incomplete publication request")
            return target, specifications, images
        except BaseException:
            for image in images.values():
                image.close()
            raise

    def close(self) -> tuple[Thread, ...]:
        with self._lock:
            self._stop.set()
            deadlines = tuple(self._deadlines)
        for guard in deadlines:
            guard.abort()
        listener = self._listener
        if listener is not None:
            # Wake the blocking accept before closing, including on Windows named pipes.
            try:
                if self._address is not None:
                    _wake_listener(self._address)
            except OSError:
                pass
            try:
                listener.close()
            except OSError:
                _LOG.exception("Cannot close runtime-control listener")
            self._listener = None
        if self._thread is not None and self._thread.ident is not None:
            self._thread.join(timeout=2)
        if self._metadata is not None:
            try:
                with self._metadata_path.open("rb") as file:
                    same = file.read(_MAX_METADATA + 1) == self._metadata
                if same:
                    self._metadata_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                _LOG.exception("Cannot remove runtime-control metadata")
        if self._address is not None and os.name != "nt" and not self._address.startswith("\0"):
            try:
                Path(self._address).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                _LOG.exception("Cannot remove runtime-control socket")
        with self._lock:
            pending = [thread for thread in self._handlers if thread.is_alive()]
        if self._thread is not None and self._thread.is_alive():
            pending.append(self._thread)
        return tuple(pending)


class RuntimeControlClient:
    """One-shot local client; publication results are never automatically replayed."""

    def __init__(self, metadata_path: Path) -> None:
        self._metadata_path = Path(metadata_path)

    def _connect(self) -> Connection:
        connection = None
        try:
            _validate_metadata_directory(self._metadata_path.parent)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            fd = os.open(self._metadata_path, flags)
            with os.fdopen(fd, "rb") as file:
                details = os.fstat(file.fileno())
                if not stat.S_ISREG(details.st_mode) or (
                    os.name != "nt" and (details.st_uid != os.geteuid() or details.st_mode & 0o077)
                ):
                    raise RuntimeProtocolError("runtime metadata is not private")
                metadata = _decode(file.read(_MAX_METADATA + 1))
            if set(metadata) != {"version", "family", "address", "credential"}:
                raise RuntimeProtocolError("invalid runtime metadata")
            if type(metadata["version"]) is not int or metadata["version"] != _VERSION:
                raise RuntimeUnsupportedProtocol("unsupported runtime-control protocol")
            family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
            if metadata["family"] != family:
                raise RuntimeProtocolError("invalid runtime endpoint")
            address = _validated_address(self._metadata_path, family, metadata["address"])
            if (
                not isinstance(metadata["credential"], str)
                or re.fullmatch(r"[0-9a-f]{64}", metadata["credential"]) is None
            ):
                raise RuntimeProtocolError("invalid runtime credential")
            connection = Client(address, family=family)
            _set_socket_timeouts(connection)
        except (OSError, EOFError, ValueError) as error:
            if connection is not None:
                connection.close()
            raise RuntimeUnavailable("No resident Refrain runtime is available; start Refrain and retry.") from error
        try:
            _send(connection, {"credential": metadata["credential"]})
            response = _decode(_receive(connection))
            if response.get("status") == "authentication-failed":
                raise RuntimeAuthenticationError("runtime-control authentication failed")
            if response != {"version": _VERSION, "status": "authenticated"}:
                raise RuntimeProtocolError("invalid authentication response")
            return connection
        except (OSError, EOFError) as error:
            connection.close()
            raise RuntimeUnavailable("resident runtime connection lost") from error
        except BaseException:
            connection.close()
            raise

    def discover(self) -> tuple[dict[str, object], ...]:
        result = []
        try:
            with self._connect() as connection:
                _send(connection, {"version": _VERSION, "operation": "discover"})
                while True:
                    response = _decode(_receive(connection))
                    if response.get("version") != _VERSION:
                        raise RuntimeUnsupportedProtocol("unsupported runtime-control protocol")
                    if response == {"version": _VERSION, "status": "succeeded"}:
                        break
                    if set(response) != {"version", "status", "destination"} or response["status"] not in (
                        "destination",
                        "destination-start",
                    ):
                        raise RuntimeProtocolError("invalid discovery response")
                    record = response["destination"]
                    if (
                        not isinstance(record, dict)
                        or set(record)
                        != {
                            "identifier",
                            "output_specification",
                            "supports_transient",
                            "participating",
                            "withdrawn",
                            "available",
                        }
                        or not isinstance(record["identifier"], str)
                        or any(
                            type(record[key]) is not bool
                            for key in ("supports_transient", "participating", "withdrawn", "available")
                        )
                    ):
                        raise RuntimeProtocolError("invalid destination record")
                    if response["status"] == "destination-start":
                        if record["identifier"] != "":
                            raise RuntimeProtocolError("invalid destination record")
                        parts = []
                        while True:
                            part = _decode(_receive(connection))
                            if part == {"version": _VERSION, "status": "destination-end"}:
                                break
                            if (
                                set(part) != {"version", "status", "value"}
                                or part["version"] != _VERSION
                                or part["status"] != "identifier-part"
                                or not isinstance(part["value"], str)
                                or not 1 <= len(part["value"]) <= _IDENTIFIER_CHUNK
                            ):
                                raise RuntimeProtocolError("invalid destination identifier")
                            parts.append(part["value"])
                        if not parts:
                            raise RuntimeProtocolError("invalid destination identifier")
                        record["identifier"] = "".join(parts)
                    result.append({**record, "output_specification": _spec_from_wire(record["output_specification"])})
        except (OSError, EOFError) as error:
            raise RuntimeUnavailable("resident runtime connection lost") from error
        return tuple(result)

    def refresh(self, on_accepted: Callable[[], object] | None = None) -> PublicationResult:
        return self._publish({"version": _VERSION, "operation": "refresh"}, (), on_accepted)

    def publish_transient(
        self,
        destinations: str | list[str] | tuple[str, ...],
        specifications: Mapping[str, ResolvedOutputSpecification],
        images: Mapping[ResolvedOutputSpecification, Image.Image],
        on_accepted: Callable[[], object] | None = None,
    ) -> PublicationResult:
        target = (
            destinations
            if destinations == "all"
            else [destinations] if isinstance(destinations, str) else list(destinations)
        )
        if any(not _supports_transient_spec(spec) for spec in specifications.values()):
            return PublicationResult(PublicationStatus.UNSUPPORTED, {})
        payloads = []
        descriptors = []
        if len(images) > _MAX_IMAGES:
            raise RuntimeProtocolError("too many images")
        total_pixels = 0
        for spec, image in images.items():
            _spec_from_wire(_spec_to_wire(spec))
            if not isinstance(image, Image.Image) or image.mode != "RGB" or image.size != spec.requested_output_size:
                raise RuntimeProtocolError("image must be RGB and match the specification")
            total_pixels += image.width * image.height
            if total_pixels > _MAX_TOTAL_PIXELS:
                raise RuntimeProtocolError("images exceed transport pixel limit")
            with _BoundedImageBuffer() as buffer:
                image.save(buffer, format="PNG")
                data = buffer.getvalue()
            if len(data) > _MAX_IMAGE_BYTES:
                raise RuntimeProtocolError("image exceeds transport limit")
            payloads.append(data)
            descriptors.append({"specification": _spec_to_wire(spec), "encoding": "png", "length": len(data)})
        if sum(map(len, payloads)) > _MAX_TOTAL_BYTES:
            raise RuntimeProtocolError("images exceed transport limit")
        request = {
            "version": _VERSION,
            "operation": "publish",
            "preflight": True,
            "target": target,
            "specifications": {key: _spec_to_wire(spec) for key, spec in specifications.items()},
            "images": descriptors,
        }
        return self._publish(request, payloads, on_accepted)

    def _publish(self, request: dict, payloads, on_accepted) -> PublicationResult:
        connection = self._connect()
        submitted = False
        try:
            if request["operation"] == "refresh":
                submitted = True
            _send(connection, request)
            if request["operation"] == "publish":
                response = _decode(_receive(connection, wait_timeout=_MAX_REQUEST_TIME))
                if response != {"version": _VERSION, "status": "ready"}:
                    result = _receive_result(connection, initial_response=response)
                    if result.status is PublicationStatus.ACCEPTED:
                        raise RuntimeProtocolError("publication accepted before image transfer")
                    return result
            for payload in payloads:
                connection.send_bytes(payload)
            # After this point, loss cannot establish whether admission occurred.
            submitted = True
            if request["operation"] == "publish":
                _send(connection, {"commit": True})
            result = _receive_result(connection)
            if result.status is not PublicationStatus.ACCEPTED:
                return result
            if on_accepted is not None:
                on_accepted()
            # Publication may take arbitrarily long; do not time out an accepted operation.
            _set_socket_timeouts(connection, 0)
            try:
                terminal = _receive_result(connection, terminal=True)
                if terminal.status is PublicationStatus.ACCEPTED:
                    raise RuntimeProtocolError("nonterminal publication response")
            except RuntimeProtocolError as error:
                raise RuntimeUnconfirmed("publication outcome is unconfirmed; do not automatically retry") from error
            return terminal
        except (OSError, EOFError) as error:
            if submitted:
                raise RuntimeUnconfirmed("publication outcome is unconfirmed; do not automatically retry") from error
            raise RuntimeUnavailable("resident runtime connection lost before submission") from error
        except RuntimeProtocolError as error:
            if submitted and str(error) == "control request timed out":
                raise RuntimeUnconfirmed("publication outcome is unconfirmed; do not automatically retry") from error
            raise
        finally:
            connection.close()

"""Independent configuration and publication access for the image server."""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NoReturn

import yaml

from ._yaml import load_yaml, yaml_error_location
from .config import ApplicationConfigurationError, ConfigurationDiagnostic, _known_fields
from .paths import ApplicationPaths, resolve_application_paths
from .publication_storage import PublicationDataset, PublicationStorageError, PublicationStore

_LOGGER = logging.getLogger(__name__)
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080


@dataclass(frozen=True)
class ImageServerConfiguration:
    """Validated consumer settings and explicitly selected publication destinations."""

    file: Path
    destinations: tuple[str, ...]
    publication_root: Path
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT

    def read_current(self, destination_id: str, *, cancelled: Callable[[], bool] | None = None) -> PublicationDataset:
        """Read a configured destination's complete, verified current dataset."""
        if destination_id not in self.destinations:
            raise PublicationStorageError(f"destination is not configured for the image server: {destination_id!r}")
        return PublicationStore(self.publication_root).read_current(destination_id, cancelled=cancelled)


def _valid_host(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        ipaddress.ip_address(value)
        return "%" not in value
    except ValueError:
        pass
    try:
        hostname = value.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if hostname.endswith("."):
        hostname = hostname[:-1]
    return 1 <= len(hostname) <= 253 and all(_HOST_LABEL.fullmatch(label) for label in hostname.split("."))


def load_image_server_config(
    config_file: str | Path | None = None, *, application_paths: ApplicationPaths | None = None
) -> ImageServerConfiguration:
    """Load only the configuration fields owned by the independent image server."""
    paths = application_paths
    if config_file is None:
        paths = paths or resolve_application_paths()
        config_file = paths.config_file
    file = Path(config_file).absolute()
    diagnostics: list[ConfigurationDiagnostic] = []
    fatal: list[ConfigurationDiagnostic] = []

    def report(field: str, message: str, severity: int = logging.WARNING) -> None:
        diagnostic = ConfigurationDiagnostic(file, field, message, severity)
        diagnostics.append(diagnostic)
        if severity >= logging.ERROR:
            fatal.append(diagnostic)

    def finish() -> None:
        for diagnostic in diagnostics:
            _LOGGER.log(diagnostic.severity, "%s", diagnostic)
        if fatal:
            raise ApplicationConfigurationError(tuple(fatal))

    def reject_document(error: Exception | None = None) -> NoReturn:
        for diagnostic in diagnostics:
            _LOGGER.log(diagnostic.severity, "%s", diagnostic)
        raise ApplicationConfigurationError(tuple(fatal)) from error

    try:
        data = load_yaml(file.read_text(encoding="utf-8"), allow_non_string_keys=True)
    except OSError as error:
        report("$", f"cannot read UTF-8 YAML file: {error}", logging.ERROR)
        reject_document(error)
    except UnicodeError:
        report("$", "cannot read UTF-8 YAML file: invalid UTF-8 encoding", logging.ERROR)
        reject_document()
    except yaml.YAMLError as error:
        location = yaml_error_location(error)
        report("$", f"invalid or unsupported YAML{f' at {location}' if location else ''}", logging.ERROR)
        reject_document()
    if not isinstance(data, dict):
        report("$", "must contain one top-level mapping", logging.ERROR)
        reject_document()

    section = data.get("image-server")
    if not isinstance(section, dict):
        report("image-server", "is required and must be a mapping", logging.ERROR)
        section = {}
    _known_fields(section, {"destinations", "host", "port"}, "image-server", report)
    selected = section.get("destinations")
    if not isinstance(selected, list) or not selected:
        report("image-server.destinations", "is required and must be a nonempty sequence", logging.ERROR)
        selected = []

    destinations = data.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        report("destinations", "is required and must be a nonempty sequence", logging.ERROR)
        destinations = []

    accepted: list[str] = []
    for index, identifier in enumerate(selected):
        field = f"image-server.destinations[{index}]"
        try:
            identifier = PublicationStore._destination_id(identifier)
        except PublicationStorageError as error:
            report(field, str(error), logging.ERROR)
            continue
        if identifier in accepted:
            report(field, f"duplicates destination ID {identifier!r}", logging.ERROR)
            continue
        accepted.append(identifier)
        matching = [item for item in destinations if isinstance(item, dict) and item.get("id") == identifier]
        if len(matching) != 1 or matching[0].get("type") != "publish":
            report(field, "must identify exactly one configured publish destination", logging.ERROR)
            continue
        collisions = [
            item
            for item in destinations
            if isinstance(item, dict)
            and item.get("type") == "publish"
            and isinstance(item.get("id"), str)
            and item["id"].casefold() == identifier.casefold()
        ]
        if len(collisions) != 1:
            report(field, "conflicts with a case-insensitive publish destination directory", logging.ERROR)

    host = section.get("host", _DEFAULT_HOST)
    if not _valid_host(host):
        report("image-server.host", f"must be an IP address or valid hostname; using {_DEFAULT_HOST}")
        host = _DEFAULT_HOST
    port = section.get("port", _DEFAULT_PORT)
    if type(port) is not int or not 1 <= port <= 65535:
        report("image-server.port", f"must be an integer from 1 to 65535; using {_DEFAULT_PORT}")
        port = _DEFAULT_PORT

    storage = data.get("storage", {})
    if not isinstance(storage, dict):
        report("storage", "must be a mapping", logging.ERROR)
        storage = {}
    root = None
    if "publish" in storage:
        value = storage["publish"]
        if not isinstance(value, str) or not value or "\0" in value:
            report("storage.publish", "must be a nonempty path string without NUL characters", logging.ERROR)
        else:
            root = Path(value)
            if not root.is_absolute():
                root = file.parent / root
            if not root.is_absolute():
                report(
                    "storage.publish", "must resolve to an absolute path relative to the configuration", logging.ERROR
                )
    finish()
    if root is None:
        paths = paths or resolve_application_paths()
        root = Path(paths.publish_directory)
    assert isinstance(host, str) and isinstance(port, int)
    return ImageServerConfiguration(file, tuple(accepted), root, host, port)

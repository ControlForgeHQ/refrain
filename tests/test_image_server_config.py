from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from refrain.config import ApplicationConfigurationError, load_application_config
from refrain.image_server_config import load_image_server_config
from refrain.paths import resolve_application_paths
from refrain.publication_storage import PublicationStorageError


def _load(tmp_path: Path, data: object):
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_image_server_config(file)


def _config(**section: object) -> dict[str, object]:
    return {
        "destinations": [{"id": "screen", "type": "publish"}],
        "image-server": {"destinations": ["screen"], **section},
    }


def test_defaults_and_isolation_from_resident_fields(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    data = _config()
    data.update(
        fonts=None,
        scheduling={"reveal": False},
        unknown={"invalid": True},
        storage={"content": [], "state": False, "artifacts": 123, "publish": "output"},
    )
    data["destinations"] = [
        {"id": "screen", "type": "publish", "audience": None, "resolution": "bad", "unknown": True},
        {"id": [], "type": None},
    ]
    with caplog.at_level(logging.INFO):
        config = _load(tmp_path, data)
    assert config.destinations == ("screen",)
    assert config.host == "127.0.0.1" and config.port == 8080
    assert config.publication_root == tmp_path / "output"
    assert not caplog.records
    assert not config.publication_root.exists()
    with pytest.raises(PublicationStorageError):
        config.read_current("screen")
    with pytest.raises(PublicationStorageError, match="not configured"):
        config.read_current("other")
    assert not config.publication_root.exists()


@pytest.mark.parametrize("host", ["localhost", "example.org.", "bücher.example", "127.0.0.1", "::1", "2001:db8::1"])
def test_valid_host_and_port(tmp_path: Path, host: str, caplog: pytest.LogCaptureFixture) -> None:
    config = _load(tmp_path, _config(host=host, port=65535))
    assert (config.host, config.port) == (host, 65535)
    assert not caplog.records


@pytest.mark.parametrize("host", [None, "", [], "bad host", "-bad.example", "bad..example", "a" * 64, "::1%lo"])
@pytest.mark.parametrize("port", [None, True, 0, 65536, 1.5, "8080"])
def test_invalid_optional_values_warn_and_default(tmp_path: Path, host: object, port: object, caplog) -> None:
    config = _load(tmp_path, _config(host=host, port=port))
    assert (config.host, config.port) == ("127.0.0.1", 8080)
    assert "image-server.host" in caplog.text and "image-server.port" in caplog.text


@pytest.mark.parametrize(
    "selected,destinations",
    [
        ([], [{"id": "screen", "type": "publish"}]),
        (["screen", "screen"], [{"id": "screen", "type": "publish"}]),
        ([None], [{"id": "screen", "type": "publish"}]),
        (["@all"], [{"id": "screen", "type": "publish"}]),
        (["CON"], [{"id": "CON", "type": "publish"}]),
        (["x" * 256], [{"id": "x" * 256, "type": "publish"}]),
        (["missing"], [{"id": "screen", "type": "publish"}]),
        (["screen"], [{"id": "screen", "type": "window"}]),
        (["screen"], [{"id": "screen", "type": "publish"}, {"id": "screen", "type": "window"}]),
        (["screen"], [{"id": "screen", "type": "publish"}, {"id": "SCREEN", "type": "publish"}]),
    ],
)
def test_invalid_destinations_are_fatal(tmp_path: Path, selected: object, destinations: object) -> None:
    with pytest.raises(ApplicationConfigurationError, match="image-server.destinations"):
        _load(tmp_path, {"image-server": {"destinations": selected}, "destinations": destinations})


def test_unrelated_destination_collisions_are_ignored(tmp_path: Path) -> None:
    data = _config()
    data["destinations"] += [{"id": "other", "type": "publish"}, {"id": "OTHER", "type": "publish"}]
    assert _load(tmp_path, data).destinations == ("screen",)


@pytest.mark.parametrize("section", [None, [], {}, {"destinations": None}])
def test_required_section_is_fatal(tmp_path: Path, section: object) -> None:
    with pytest.raises(ApplicationConfigurationError, match="image-server"):
        _load(tmp_path, {"image-server": section})


@pytest.mark.parametrize("storage", [None, [], {"publish": ""}, {"publish": False}])
def test_invalid_publication_storage_is_fatal(tmp_path: Path, storage: object) -> None:
    data = _config()
    data["storage"] = storage
    with pytest.raises(ApplicationConfigurationError, match="storage"):
        _load(tmp_path, data)


def test_standard_and_absolute_publication_roots(tmp_path: Path) -> None:
    paths = resolve_application_paths(
        platform="linux",
        environ={"XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_STATE_HOME": str(tmp_path / "state")},
        home=tmp_path,
    )
    file = Path(paths.config_file)
    file.parent.mkdir(parents=True)
    file.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    assert load_image_server_config(application_paths=paths).publication_root == paths.publish_directory
    data = _config()
    data["storage"] = {"publish": str(tmp_path / "absolute")}
    assert _load(tmp_path, data).publication_root == tmp_path / "absolute"


@pytest.mark.parametrize(
    "contents",
    [
        "[]",
        "destinations: []\n---\nimage-server: {}",
        "x: &anchor 1\ny: *anchor",
        "x: 1\nx: 2",
        "x: !unsupported value",
        "x: {<<: {a: 1}}",
    ],
)
def test_shared_yaml_document_rules(tmp_path: Path, contents: str) -> None:
    file = tmp_path / "config.yaml"
    file.write_text(contents, encoding="utf-8")
    with pytest.raises(ApplicationConfigurationError):
        load_image_server_config(file)


def test_resident_ignores_image_server_section(tmp_path: Path, caplog) -> None:
    data = {
        "destinations": [{"id": "desktop", "type": "window", "audience": "internal"}],
        "fonts": {"pools": {"default": ["@builtin"]}},
        "image-server": {"destinations": None, "host": [], "port": False, "unknown": 1},
    }
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(data), encoding="utf-8")
    load_application_config(file)
    assert "image-server" not in caplog.text

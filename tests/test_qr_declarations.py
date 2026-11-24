from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from refrain.config import (
    DestinationPresentation,
    DisplayOutputConfiguration,
    PreparedImageVariantKey,
    load_application_config,
)
from refrain.content import ContentQRDeclaration, load_content_library, resolve_qr_payloads, validate_qr_payload
from refrain.geometry import ResolvedOutputSpecification


def _write_yaml(path: Path, data: object) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _config(path: Path, presentation: object = None, *, supplied: bool = True):
    data = {
        "destinations": [{"id": "test", "type": "publish", "audience": "internal"}],
        "fonts": {"pools": {"default": ["@builtin"]}},
    }
    if supplied:
        data["presentation"] = presentation
    return load_application_config(_write_yaml(path, data))


def _entry(path: Path, qr: object, *, supplied: bool = True):
    data = {"id": "example", "quotations": ["one", "two"]}
    if supplied:
        data["qr"] = qr
    _write_yaml(path, data)
    return load_content_library(path.parent)[0]


def test_omitted_and_null_config_defaults_are_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        omitted = _config(tmp_path / "omitted.yaml", supplied=False)
        explicit = _config(tmp_path / "null.yaml", {"qr": {"external": None, "internal": None}})
    assert dict(omitted.qr_defaults) == dict(explicit.qr_defaults) == {"external": None, "internal": None}
    assert not [record for record in caplog.records if "presentation.qr" in record.message]
    with pytest.raises(TypeError):
        omitted.qr_defaults["external"] = "changed"


@pytest.mark.parametrize("value", ["", "é" * 32, True, 123, [], {}])
def test_invalid_config_audience_preserves_other_default(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, value: object
) -> None:
    config = _config(tmp_path / "config.yaml", {"qr": {"external": value, "internal": "  exact\n"}})
    assert dict(config.qr_defaults) == {"external": None, "internal": "  exact\n"}
    assert "presentation.qr.external" in caplog.text
    assert str(tmp_path / "config.yaml") in caplog.text
    assert "using null" in caplog.text


@pytest.mark.parametrize("value", [None, [], "bad", True])
def test_invalid_config_mapping_uses_null_defaults(tmp_path: Path, caplog: pytest.LogCaptureFixture, value) -> None:
    config = _config(tmp_path / "config.yaml", {"qr": value})
    assert dict(config.qr_defaults) == {"external": None, "internal": None}
    assert "presentation.qr" in caplog.text
    assert "using null for both audiences" in caplog.text


def test_unknown_qr_config_keys_warn_and_are_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    config = _config(tmp_path / "config.yaml", {"qr": {"external": "unchanged", "enabled": False}})
    assert config.qr_defaults["external"] == "unchanged"
    assert "presentation.qr.enabled" in caplog.text


def test_content_preserves_payload_null_and_first_valid_per_audience(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entry = _entry(
        tmp_path / "entry.yaml",
        [
            {"visibility": ["external"]},
            {"visibility": ["external"], "payload": None},
            {"visibility": ["external"], "payload": "discarded"},
            {"visibility": ["internal"], "payload": " \nopaque é\t"},
            {"visibility": ["internal"], "payload": None},
        ],
    )
    assert entry.qr == (
        ContentQRDeclaration(("external",), None),
        ContentQRDeclaration(("internal",), " \nopaque é\t"),
    )
    assert len(entry.quotations) == 2
    assert "qr[0]" in caplog.text and "qr[2]" in caplog.text and "qr[4]" in caplog.text
    assert str(tmp_path / "entry.yaml") in caplog.text
    assert "ignored" in caplog.text and "entry is excluded" not in caplog.text
    with pytest.raises(FrozenInstanceError):
        entry.qr[0].payload = "changed"


@pytest.mark.parametrize(
    "member",
    [
        None,
        [],
        {},
        {"visibility": ["external"]},
        {"payload": "x"},
        {"visibility": ["external", "internal"], "payload": "x"},
        {"visibility": "external", "payload": "x"},
        {"visibility": ["unknown"], "payload": "x"},
        {"visibility": ["external"], "payload": ""},
        {"visibility": ["external"], "payload": False},
        {"visibility": ["external"], "payload": "é" * 32},
        {"visibility": ["external"], "payload": "x", "extra": 1},
    ],
)
def test_invalid_content_declarations_do_not_suppress_inheritance(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, member: object
) -> None:
    entry = _entry(tmp_path / "entry.yaml", [member, {"visibility": ["internal"], "payload": "ok"}])
    assert entry.qr == (ContentQRDeclaration(("internal",), "ok"),)
    assert resolve_qr_payloads({"external": "default"}, entry.qr) == (
        ContentQRDeclaration(("external",), "default"),
        ContentQRDeclaration(("internal",), "ok"),
    )
    assert "qr[0]" in caplog.text


@pytest.mark.parametrize("qr", [None, {}, "bad", 1])
def test_invalid_content_collection_is_recoverable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, qr: object
) -> None:
    entry = _entry(tmp_path / "entry.yaml", qr)
    assert entry.qr == ()
    assert "qr" in caplog.text and "ignored" in caplog.text


def test_resolve_precedence_and_exact_payloads() -> None:
    defaults = {"external": "  default\n", "internal": "int"}
    declarations = (ContentQRDeclaration(("external",), None), ContentQRDeclaration(("internal",), "entry"))
    assert resolve_qr_payloads(defaults, declarations) == (ContentQRDeclaration(("internal",), "entry"),)
    assert resolve_qr_payloads(defaults, declarations, overrides={"external": "viewer", "internal": None}) == (
        ContentQRDeclaration(("external",), "viewer"),
    )
    assert resolve_qr_payloads(defaults, overrides={})[0].payload == "  default\n"
    with pytest.raises(ValueError):
        resolve_qr_payloads(defaults, overrides={"external": ""})
    with pytest.raises(ValueError):
        resolve_qr_payloads(defaults, overrides={"other": "x"})
    with pytest.raises(ValueError):
        resolve_qr_payloads(defaults, declarations + declarations)


def test_utf8_byte_boundaries_and_unencodable_text() -> None:
    assert validate_qr_payload("é" * 31) == "é" * 31
    assert validate_qr_payload(" " * 62) == " " * 62
    assert validate_qr_payload(None) is None
    for payload in ("é" * 32, "x" * 63, "\ud800", ""):
        with pytest.raises(ValueError):
            validate_qr_payload(payload)


def test_shipped_qr_configuration() -> None:
    path = Path(__file__).parents[1] / "src" / "refrain" / "config.default.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    url = "https://github.com/ControlForgeHQ/refrain"
    assert data["presentation"]["qr"] == {"external": url, "internal": url}


def test_output_keys_distinguish_payloads_but_not_audiences() -> None:
    specification = ResolvedOutputSpecification("16:10", (320, 200))
    external = DisplayOutputConfiguration("external", specification, audience="external")
    internal = DisplayOutputConfiguration("internal", specification, audience="internal")
    assert external.prepared_image_key_for_qr("same") == internal.prepared_image_key_for_qr("same")
    assert external.prepared_image_key_for_qr("same") != internal.prepared_image_key_for_qr("different")
    assert external.prepared_image_key_for_qr("same") == PreparedImageVariantKey(
        specification, DestinationPresentation(), "same"
    )
    assert external.prepared_image_key_for_qr(None) == external.prepared_image_key == specification
    with pytest.raises(ValueError):
        external.prepared_image_key_for_qr("")


def test_qr_suppression_normalizes_output_key() -> None:
    specification = ResolvedOutputSpecification("16:10", (320, 200))
    output = DisplayOutputConfiguration(
        "suppressed", specification, DestinationPresentation(qr_enabled=False), audience="external"
    )
    assert output.prepared_image_key_for_qr("payload") == output.prepared_image_key_for_qr(None)

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import refrain.__main__ as cli
import refrain.viewer as viewer
from refrain.display.coordinator import PublicationResult, PublicationStatus
from refrain.geometry import ResolvedOutputSpecification
from refrain.runtime_control import (
    RuntimeAuthenticationError,
    RuntimeProtocolError,
    RuntimeUnavailable,
    RuntimeUnconfirmed,
    RuntimeUnsupportedProtocol,
)


@pytest.fixture
def paths(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(control_metadata_file=tmp_path / ".refrain-control" / "endpoint.json")


def test_refresh_is_a_lock_free_runtime_control_client(
    paths: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = {}

    class Client:
        def __init__(self, metadata_path: Path) -> None:
            seen["metadata_path"] = metadata_path

        def refresh(self, *, on_accepted):
            seen["refresh_called"] = True
            on_accepted()
            assert "Refresh accepted; publication has begun." in capsys.readouterr().out
            return PublicationResult(PublicationStatus.SUCCEEDED, {"opaque:destination": (True, None)})

    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "RuntimeControlClient", Client)
    monkeypatch.setattr(cli, "_installation_ownership", lambda *_: pytest.fail("installation ownership acquired"))
    monkeypatch.setattr(cli, "load_application_config", lambda *_: pytest.fail("configuration loaded"))

    assert cli.main(["--refresh"]) == 0
    assert seen == {"metadata_path": Path(paths.control_metadata_file), "refresh_called": True}
    assert "Refresh completed successfully." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("status", "destinations", "diagnostic"),
    [
        (PublicationStatus.BUSY, {}, "busy"),
        (PublicationStatus.FAILED, {"screen:one": (False, "device timed out")}, "device timed out"),
        (PublicationStatus.STOPPING, {}, "stopping"),
    ],
)
def test_refresh_terminal_failures_are_reported(
    status: PublicationStatus,
    destinations: dict,
    diagnostic: str,
    paths: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def refresh(self, *, on_accepted):
            on_accepted()
            return PublicationResult(status, destinations)

    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "RuntimeControlClient", Client)
    assert cli.main(["--refresh"]) == 1
    assert diagnostic in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "diagnostic"),
    [
        (RuntimeUnavailable("No resident Refrain runtime is available; start Refrain and retry."), "No resident"),
        (RuntimeAuthenticationError("runtime-control authentication failed"), "authentication failed"),
        (RuntimeUnsupportedProtocol("unsupported runtime-control protocol"), "versions are compatible"),
        (RuntimeProtocolError("invalid publication response"), "protocol error"),
        (RuntimeUnconfirmed("publication outcome is unconfirmed"), "publication may have occurred"),
    ],
)
def test_refresh_control_errors_are_actionable(
    error: Exception,
    diagnostic: str,
    paths: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def refresh(self, **_kwargs):
            raise error

    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "RuntimeControlClient", Client)
    assert cli.main(["--refresh"]) == 1
    assert diagnostic in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--refresh", "--config", "custom.yaml"],
        ["--refresh", "--demo", "5"],
        ["--refresh", "--initialize"],
        ["--refresh", "--reset"],
        ["--refresh", "--purge"],
    ],
)
def test_refresh_rejects_conflicting_modes(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    assert "--refresh" in capsys.readouterr().err


def _destination(
    identifier: str,
    *,
    participating: bool = True,
    withdrawn: bool = False,
    available: bool = True,
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "output_specification": ResolvedOutputSpecification("16:9", (1920, 1080)),
        "supports_transient": True,
        "participating": participating,
        "withdrawn": withdrawn,
        "available": available,
    }


def test_list_destinations_uses_only_runtime_discovery_and_preserves_runtime_values(
    paths: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    records = (
        _destination("opaque:screen-A"),
        _destination("screen-B", participating=False, withdrawn=True),
        _destination("screen-C", available=False),
    )
    seen = {}

    class Client:
        def __init__(self, metadata_path: Path) -> None:
            seen["metadata_path"] = metadata_path

        def discover(self):
            seen["discovered"] = True
            return records

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("viewer configuration loaded"))
    monkeypatch.setattr(viewer, "load_content_library", lambda *_: pytest.fail("viewer content loaded"))
    monkeypatch.setattr(viewer, "render_preview", lambda *_args, **_kwargs: pytest.fail("presentation rendered"))

    assert viewer.main(["--list-destinations"]) == 0
    output = capsys.readouterr().out
    assert seen == {"metadata_path": Path(paths.control_metadata_file), "discovered": True}
    assert "opaque:screen-A" in output
    assert "16:9" in output and "1920x1080" in output
    assert "Transient" in output and "yes" in output
    assert "participating" in output and "not participating" in output
    assert "unavailable/failed" in output and "Withdrawn" in output


def test_empty_discovery_is_reported_without_failure(
    paths: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return ()

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    assert viewer.main(["--list-destinations"]) == 0
    assert "No destinations are configured" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("error", "diagnostic"),
    [
        (RuntimeUnavailable("No resident Refrain runtime is available; start Refrain and retry."), "No resident"),
        (RuntimeAuthenticationError("runtime-control authentication failed"), "authentication failed"),
        (RuntimeUnsupportedProtocol("unsupported runtime-control protocol"), "versions are compatible"),
        (RuntimeProtocolError("invalid destination record"), "protocol error"),
    ],
)
def test_discovery_control_errors_are_actionable(
    error: Exception,
    diagnostic: str,
    paths: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            raise error

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    assert viewer.main(["--list-destinations"]) == 1
    assert diagnostic in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--config", "custom.yaml"],
        ["--entry", "example"],
        ["--font", "lora"],
        ["--quotation-face", "regular"],
        ["--source-face", "regular"],
        ["--attribution-face", "regular"],
        ["--min-font-size", "48"],
        ["--max-font-size", "120"],
        ["--background", "linen"],
        ["--decoration", "border"],
        ["--text-color", "black"],
        ["--tint", "gold"],
        ["--style", "centered"],
        ["--qr"],
        ["--no-qr"],
        ["--aspect", "16:10"],
        ["--resolution", "320", "200"],
        ["--output", "preview.png"],
        ["--window"],
        ["--debug-layout"],
    ],
)
def test_list_destinations_rejects_local_viewer_options(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        viewer.main(["--list-destinations", *arguments])
    assert error.value.code == 2
    assert "standalone" in capsys.readouterr().err

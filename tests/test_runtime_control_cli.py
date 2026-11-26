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


@pytest.mark.parametrize("status", [PublicationStatus.UNCONFIRMED, PublicationStatus.FAILED])
@pytest.mark.parametrize("operation", ["push", "refresh"])
def test_uncertain_destination_is_not_reported_as_definite_failure(status, operation, capsys):
    result = PublicationResult(status, {"one": (None, "verification unavailable"), "two": (False, "failed")})
    if operation == "push":
        exit_code = viewer._report_push_result(result, [{"identifier": "one"}, {"identifier": "two"}])
    else:
        exit_code = cli._report_refresh_result(result)
    assert exit_code == 1
    diagnostic = capsys.readouterr().err
    assert "one: outcome unconfirmed: verification unavailable" in diagnostic
    assert "two: failed" in diagnostic
    assert "do not retry automatically" in diagnostic


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
        (PublicationStatus.STALE_PRESENTATION, {}, "unavailable or changed during refresh"),
        (PublicationStatus.NO_TARGET, {}, "no destinations are participating"),
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
    available: bool | str = True,
    publication_accepted: bool = False,
    audience: str = "internal",
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "audience": audience,
        "output_specification": ResolvedOutputSpecification("16:9", (1920, 1080)),
        "supports_transient": True,
        "participating": participating,
        "withdrawn": withdrawn,
        "available": available,
        "publication_accepted": publication_accepted,
    }


def test_list_destinations_uses_only_runtime_discovery_and_preserves_runtime_values(
    paths: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    records = (
        _destination("window", publication_accepted=True, audience="external"),
        _destination("wquxga", participating=False, withdrawn=True),
        _destination("epaper-destination-with-a-long-name", available=False),
        _destination("publish", available="unknown"),
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
    lines = capsys.readouterr().out.rstrip().splitlines()
    assert seen == {"metadata_path": Path(paths.control_metadata_file), "discovered": True}
    expected_cells = (
        (
            "Destination",
            "Audience",
            "Aspect",
            "Resolution",
            "Transient",
            "Participation",
            "Delivery",
            "Publication",
            "Withdrawn",
        ),
        ("window", "external", "16:9", "1920x1080", "yes", "participating", "available", "accepted", "no"),
        ("wquxga", "internal", "16:9", "1920x1080", "yes", "not participating", "available", "not accepted", "yes"),
        (
            "epaper-destination-with-a-long-name",
            "internal",
            "16:9",
            "1920x1080",
            "yes",
            "participating",
            "unavailable/failed",
            "not accepted",
            "no",
        ),
        ("publish", "internal", "16:9", "1920x1080", "yes", "participating", "unknown", "not accepted", "no"),
    )
    assert len(lines) == len(expected_cells)
    column_starts = []
    for line, cells in zip(lines, expected_cells, strict=True):
        cursor = 0
        starts = []
        for cell in cells:
            position = line.find(cell, cursor)
            assert position >= cursor
            starts.append(position)
            cursor = position + len(cell)
        column_starts.append(starts)
    assert all(starts == column_starts[0] for starts in column_starts[1:])


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
        ["--qr-external", "external payload"],
        ["--qr-internal", "internal payload"],
        ["--audience", "external"],
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

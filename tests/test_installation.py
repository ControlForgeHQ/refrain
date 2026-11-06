from __future__ import annotations

import io
import signal
from datetime import date
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

import refrain.__main__ as cli
import refrain.installation as installation
from refrain.config import load_application_config
from refrain.content import load_content_library
from refrain.installation import (
    InitializationError,
    InstallationOperationError,
    confirm_operation,
    initialize_installation,
    purge_installation,
    reset_installation,
)
from refrain.paths import ApplicationPathError, ApplicationPaths, resolve_application_paths


def _paths(root: Path) -> ApplicationPaths:
    config_directory = root / "config" / "refrain"
    state_directory = root / "state" / "refrain"
    cache_directory = root / "cache" / "refrain"
    return ApplicationPaths(
        config_directory=config_directory,
        config_file=config_directory / "config.yaml",
        content_directory=config_directory / "content",
        operational_directory=state_directory,
        state_directory=state_directory,
        state_file=state_directory / "state.json",
        history_file=state_directory / "global-history.jsonl",
        cache_directory=cache_directory,
        artifacts_directory=cache_directory / "artifacts",
    )


def test_linux_default_paths_and_cwd_independence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    expected = resolve_application_paths(platform="linux", environ={}, home=home)
    work = tmp_path / "elsewhere"
    work.mkdir()
    monkeypatch.chdir(work)
    actual = resolve_application_paths(platform="linux", environ={}, home=home)

    assert actual == expected
    assert actual.config_file == home / ".config/refrain/config.yaml"
    assert actual.content_directory == home / ".config/refrain/content"
    assert actual.state_file == home / ".local/state/refrain/state.json"
    assert actual.history_file == home / ".local/state/refrain/global-history.jsonl"
    assert actual.artifacts_directory == home / ".cache/refrain/artifacts"


def test_linux_paths_respect_absolute_xdg_overrides(tmp_path: Path) -> None:
    config = tmp_path / "cfg"
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    paths = resolve_application_paths(
        platform="linux",
        environ={
            "XDG_CONFIG_HOME": str(config),
            "XDG_STATE_HOME": str(state),
            "XDG_CACHE_HOME": str(cache),
        },
        home=tmp_path / "home",
    )

    assert paths.config_file == config / "refrain/config.yaml"
    assert paths.state_file == state / "refrain/state.json"
    assert paths.artifacts_directory == cache / "refrain/artifacts"


def test_absolute_xdg_overrides_do_not_require_a_home_directory(tmp_path: Path) -> None:
    paths = resolve_application_paths(
        platform="linux",
        environ={
            "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        home="relative-home",
    )
    assert paths.config_file == tmp_path / "cfg/refrain/config.yaml"


@pytest.mark.parametrize("value", [None, "", "relative/path"])
@pytest.mark.parametrize(
    "variable,fallback",
    [
        ("XDG_CONFIG_HOME", ".config"),
        ("XDG_STATE_HOME", ".local/state"),
        ("XDG_CACHE_HOME", ".cache"),
    ],
)
def test_linux_invalid_xdg_values_use_documented_fallback(
    tmp_path: Path, variable: str, fallback: str, value: str | None
) -> None:
    home = tmp_path / "home"
    environ = {} if value is None else {variable: value}
    paths = resolve_application_paths(platform="linux", environ=environ, home=home)

    expected = home / fallback / "refrain"
    actual = {
        "XDG_CONFIG_HOME": paths.config_directory,
        "XDG_STATE_HOME": paths.state_directory,
        "XDG_CACHE_HOME": paths.cache_directory,
    }[variable]
    assert actual == expected


def test_windows_roaming_and_local_paths_are_platform_independent() -> None:
    paths = resolve_application_paths(
        platform="win32",
        environ={
            "APPDATA": r"C:\Users\Ada\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local",
        },
    )

    assert isinstance(paths.config_file, PureWindowsPath)
    assert str(paths.config_file) == r"C:\Users\Ada\AppData\Roaming\Refrain\config.yaml"
    assert str(paths.content_directory) == r"C:\Users\Ada\AppData\Roaming\Refrain\content"
    assert str(paths.state_file) == r"C:\Users\Ada\AppData\Local\Refrain\State\state.json"
    assert str(paths.history_file) == r"C:\Users\Ada\AppData\Local\Refrain\State\global-history.jsonl"
    assert str(paths.artifacts_directory) == r"C:\Users\Ada\AppData\Local\Refrain\Cache\artifacts"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, "APPDATA"),
        ({"APPDATA": r"C:\Users\Ada\AppData\Roaming"}, "LOCALAPPDATA"),
        ({"APPDATA": "relative", "LOCALAPPDATA": r"C:\Users\Ada\AppData\Local"}, "APPDATA"),
    ],
)
def test_windows_missing_or_relative_application_data_is_actionable(environ, expected: str) -> None:
    with pytest.raises(ApplicationPathError, match=expected):
        resolve_application_paths(platform="win32", environ=environ)


def test_macos_uses_user_library_locations(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = resolve_application_paths(platform="darwin", environ={}, home=home)
    assert paths.config_file == home / "Library/Application Support/Refrain/config.yaml"
    assert paths.state_file == home / "Library/Application Support/Refrain/State/state.json"
    assert paths.artifacts_directory == home / "Library/Caches/Refrain/artifacts"


def test_initialization_installs_packaged_defaults_without_empty_state_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    reports: list[str] = []
    created = initialize_installation(paths, progress=reports.append)

    assert paths.config_file.read_bytes() == (Path(installation.__file__).parent / "config.default.yaml").read_bytes()
    assert "\ncontent:\n" not in paths.config_file.read_text(encoding="utf-8")
    config = load_application_config(paths.config_file)
    assert config.content_directory == paths.content_directory
    assert [(backend.type, backend.host, backend.port) for backend in config.display_backends] == [
        ("image-server", "127.0.0.1", 8080)
    ]
    assert config.default_fonts == ("alegreya", "libre-baskerville", "lora", "orbitron", "source-sans-3")
    assert config.default_backgrounds == ("none", "aged-paper", "canvas", "cloth", "ethereal", "hex")
    assert config.default_decorations == (
        "none",
        "ethereal",
        "hex",
        "lower-flourish",
        "simple-border",
        "top-bottom-borders",
    )
    assert "timezone" not in paths.config_file.read_text(encoding="utf-8")
    entries = load_content_library(paths.content_directory)
    assert len(entries) >= 3
    assert sum(len(entry.quotations) for entry in entries) >= 4
    assert any(rule.ordinary for entry in entries for rule in entry.eligibility)
    package_content = Path(installation.__file__).parent / "sample_content"
    assert {
        path.relative_to(package_content).as_posix(): path.read_bytes()
        for path in package_content.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(paths.content_directory).as_posix(): path.read_bytes()
        for path in paths.content_directory.rglob("*")
        if path.is_file()
    }
    assert paths.state_directory.is_dir()
    assert paths.artifacts_directory.is_dir()
    assert not paths.state_file.exists()
    assert not paths.history_file.exists()
    assert any("Configuration:" in message for message in reports)
    assert any("Content:" in message for message in reports)
    assert any("State directory:" in message for message in reports)
    assert any("Artifacts:" in message for message in reports)
    assert paths.state_directory in created
    assert paths.artifacts_directory in created


def test_existing_empty_configuration_and_content_directories_are_reused(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.content_directory.mkdir()

    initialize_installation(paths)

    assert paths.config_file.is_file()
    assert load_content_library(paths.content_directory)
    assert not paths.state_file.exists()
    assert not paths.history_file.exists()


def test_existing_configuration_is_preserved_byte_for_byte(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    original = b"\xffuser configuration\r\n"
    paths.config_file.write_bytes(original)
    reports: list[str] = []

    initialize_installation(paths, progress=reports.append)

    assert paths.config_file.read_bytes() == original
    assert any("configuration preserved" in message for message in reports)


@pytest.mark.parametrize("entry_name", ["custom.yaml", ".hidden", "subdirectory"])
def test_nonempty_content_directory_is_preserved_without_samples(tmp_path: Path, entry_name: str) -> None:
    paths = _paths(tmp_path)
    paths.content_directory.mkdir(parents=True)
    entry = paths.content_directory / entry_name
    if entry_name == "subdirectory":
        entry.mkdir()
        (entry / "data").write_bytes(b"keep")
    else:
        entry.write_bytes(b"keep")
    before = {
        path.relative_to(paths.content_directory): path.read_bytes()
        for path in paths.content_directory.rglob("*")
        if path.is_file()
    }

    reports: list[str] = []
    initialize_installation(paths, progress=reports.append)

    assert {
        path.relative_to(paths.content_directory): path.read_bytes()
        for path in paths.content_directory.rglob("*")
        if path.is_file()
    } == before
    assert any("nonempty content directory preserved" in message for message in reports)


def test_existing_state_history_and_artifact_files_are_preserved(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.state_directory.mkdir(parents=True)
    paths.artifacts_directory.mkdir(parents=True)
    expected = {
        paths.state_file: b"state",
        paths.history_file: b"history",
        paths.state_directory / "global-history.2.jsonl": b"rotated history",
        paths.artifacts_directory / "stage.png": b"prepared image",
    }
    for path, contents in expected.items():
        path.write_bytes(contents)

    initialize_installation(paths)

    assert {path: path.read_bytes() for path in expected} == expected


def test_preflight_rejects_unexpected_objects_before_writing(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.config_file.mkdir()
    paths.content_directory.parent.mkdir(parents=True, exist_ok=True)
    paths.content_directory.symlink_to(tmp_path / "elsewhere", target_is_directory=True)

    with pytest.raises(InitializationError) as error:
        initialize_installation(paths)

    assert str(paths.content_directory) in str(error.value)
    assert not paths.state_directory.exists()
    assert not paths.cache_directory.exists()


def test_preflight_reports_a_non_directory_ancestor_before_creating_anything(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    blocker = paths.operational_directory.parent
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InitializationError) as error:
        initialize_installation(paths)

    assert str(blocker) in str(error.value)
    assert not paths.config_directory.exists()
    assert not paths.cache_directory.exists()


def test_symlink_destination_is_a_conflict(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.cache_directory.parent.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    paths.cache_directory.symlink_to(unrelated, target_is_directory=True)

    with pytest.raises(InitializationError, match=str(paths.cache_directory)):
        initialize_installation(paths)
    assert list(unrelated.iterdir()) == []
    assert not paths.config_directory.exists()


@pytest.mark.parametrize(
    "destination",
    ["config_directory", "content_directory", "operational_directory", "state_directory", "cache_directory"],
)
def test_unexpected_file_destinations_are_conflicts(tmp_path: Path, destination: str) -> None:
    paths = _paths(tmp_path)
    target = Path(getattr(paths, destination))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InitializationError) as error:
        initialize_installation(paths)

    assert str(target) in str(error.value)
    assert target.read_text(encoding="utf-8") == "not a directory"
    assert not paths.state_file.exists()


def test_destination_appearing_after_preflight_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    original_create_file = installation._create_file

    def create_after_preflight(path: Path, contents: bytes, created: list[Path], owned_directories: set[Path]) -> None:
        if path == paths.config_file:
            path.write_bytes(b"racing user data")
        original_create_file(path, contents, created, owned_directories)

    monkeypatch.setattr(installation, "_create_file", create_after_preflight)
    with pytest.raises(InitializationError, match="initialization failed"):
        initialize_installation(paths)
    assert paths.config_file.read_bytes() == b"racing user data"
    assert not paths.state_directory.exists()


def test_partial_initialization_failure_reports_created_data_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    shared_data = paths.config_directory.parent / "other-user-file.txt"
    shared_data.parent.mkdir(parents=True)
    shared_data.write_text("preserve", encoding="utf-8")
    original_create_file = installation._create_file

    def fail_on_sample(path: Path, contents: bytes, created: list[Path], owned_directories: set[Path]) -> None:
        if path.parent == paths.content_directory:
            raise OSError("disk full")
        original_create_file(path, contents, created, owned_directories)

    monkeypatch.setattr(installation, "_create_file", fail_on_sample)
    with pytest.raises(InitializationError, match="Created destinations that remain in place") as error:
        initialize_installation(paths)
    assert paths.config_file.is_file()
    assert str(paths.config_file) in str(error.value)
    assert paths.content_directory.is_dir()
    assert shared_data.read_text(encoding="utf-8") == "preserve"

    monkeypatch.setattr(installation, "_create_file", original_create_file)
    initialize_installation(paths)
    assert load_content_library(paths.content_directory)


def test_repeated_initialization_succeeds_without_modifying_installed_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    initialize_installation(paths)
    before = {
        path.relative_to(paths.config_directory): path.read_bytes()
        for path in paths.config_directory.rglob("*")
        if path.is_file()
    }

    initialize_installation(paths)

    assert {
        path.relative_to(paths.config_directory): path.read_bytes()
        for path in paths.config_directory.rglob("*")
        if path.is_file()
    } == before


class _TerminalInput(io.StringIO):
    def isatty(self) -> bool:
        return True


class _TerminalOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("response", "expected"), [("RESET\n", True), ("reset\n", False), ("yes\n", False), ("", False)]
)
def test_confirmation_requires_exact_typed_value(response: str, expected: bool) -> None:
    output = _TerminalOutput()

    confirmed = confirm_operation(
        "RESET",
        "Reset explanation",
        (Path("/standard/state.json"),),
        input_stream=_TerminalInput(response),
        output_stream=output,
    )

    assert confirmed is expected
    assert "/standard/state.json" in output.getvalue()
    if not expected:
        assert "cancelled" in output.getvalue()


def test_confirmation_without_interactive_terminal_does_not_read_input() -> None:
    input_stream = io.StringIO("RESET\n")
    output = io.StringIO()

    assert not confirm_operation(
        "RESET",
        "Reset explanation",
        (),
        input_stream=input_stream,
        output_stream=output,
    )
    assert "interactive terminal is required" in output.getvalue()


def test_reset_removes_runtime_data_and_preserves_user_resources(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.state_directory.mkdir(parents=True)
    paths.artifacts_directory.mkdir(parents=True)
    config = paths.config_file
    content = paths.content_directory / "entry.yaml"
    content.parent.mkdir()
    config.write_text("custom configuration", encoding="utf-8")
    content.write_text("custom content", encoding="utf-8")
    resource = paths.config_directory / "user-font.ttf"
    resource.write_bytes(b"font")
    for path in (
        paths.state_file,
        paths.history_file,
        paths.state_directory / "global-history.1.jsonl",
        paths.artifacts_directory / "revision-1" / "stage.png",
        paths.cache_directory / "generated.tmp",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime data", encoding="utf-8")

    reset_installation(paths)

    assert config.read_text(encoding="utf-8") == "custom configuration"
    assert content.read_text(encoding="utf-8") == "custom content"
    assert resource.read_bytes() == b"font"
    assert not paths.state_file.exists()
    assert not paths.history_file.exists()
    assert not (paths.state_directory / "global-history.1.jsonl").exists()
    assert list(paths.artifacts_directory.iterdir()) == []
    assert not (paths.cache_directory / "generated.tmp").exists()
    assert paths.state_directory.is_dir()
    assert paths.artifacts_directory.is_dir()


def test_reset_is_idempotent_and_does_not_follow_artifact_links(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.artifacts_directory.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("outside", encoding="utf-8")
    (paths.artifacts_directory / "linked").symlink_to(external, target_is_directory=True)

    reset_installation(paths)
    reset_installation(paths)

    assert list(paths.artifacts_directory.iterdir()) == []
    assert (external / "keep").read_text(encoding="utf-8") == "outside"


def test_reset_rejects_linked_standard_runtime_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    paths.artifacts_directory.parent.mkdir(parents=True)
    paths.artifacts_directory.symlink_to(external, target_is_directory=True)

    with pytest.raises(InstallationOperationError, match="filesystem link"):
        reset_installation(paths)
    assert not paths.state_directory.exists()
    assert list(external.iterdir()) == []


def test_purge_removes_owned_roots_but_preserves_shared_parents_and_external_links(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.state_directory.mkdir(parents=True)
    paths.cache_directory.mkdir(parents=True)
    (paths.config_directory / "config.yaml").write_text("content: {directory: /external}", encoding="utf-8")
    (paths.config_directory / "content").mkdir()
    (paths.config_directory / "content" / "entry.yaml").write_text("user content", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("outside", encoding="utf-8")
    (paths.config_directory / "linked").symlink_to(external, target_is_directory=True)

    removed = purge_installation(paths)

    assert set(removed) == {paths.config_directory, paths.state_directory, paths.cache_directory}
    assert not paths.config_directory.exists()
    assert not paths.state_directory.exists()
    assert not paths.cache_directory.exists()
    assert paths.config_directory.parent.is_dir()
    assert paths.state_directory.parent.is_dir()
    assert paths.cache_directory.parent.is_dir()
    assert (external / "keep").read_text(encoding="utf-8") == "outside"
    assert purge_installation(paths) == removed


def test_purge_refuses_linked_installation_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("outside", encoding="utf-8")
    paths.config_directory.parent.mkdir(parents=True)
    paths.config_directory.symlink_to(external, target_is_directory=True)

    with pytest.raises(InstallationOperationError, match="filesystem link"):
        purge_installation(paths)

    assert (external / "keep").read_text(encoding="utf-8") == "outside"


def _install_cli_paths(monkeypatch: pytest.MonkeyPatch, paths: ApplicationPaths) -> None:
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    paths.config_directory.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text("packaged or test config", encoding="utf-8")
    monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)


def test_default_cli_paths_work_without_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []

    def run(config, state, artifacts, **kwargs):
        calls.append((config, state, artifacts, kwargs))

    monkeypatch.setattr(cli, "run_application", run)
    assert cli.main([]) == 0
    assert calls[0][:3] == (paths.config_file, paths.state_file, paths.artifacts_directory)
    assert calls[0][3]["history_path"] is None


def test_once_and_explicit_paths_keep_their_existing_meaning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []
    result = SimpleNamespace(
        state=SimpleNamespace(revision=1, snapshot=SimpleNamespace(display_date=date(2026, 1, 1))),
        selected_initial_quotation=True,
        presented_stage=0,
    )

    def run(config, state, artifacts, **kwargs):
        calls.append((config, state, artifacts, kwargs))
        return result

    monkeypatch.setattr(cli, "run_startup", run)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "custom.yaml").write_text("config", encoding="utf-8")
    assert cli.main(["--once", "--config", "custom.yaml", "--state", "state.json", "--artifacts", "images"]) == 0
    assert calls[0][:3] == ("custom.yaml", "state.json", "images")
    assert calls[0][3]["history_path"] is None
    assert str(tmp_path / "state.json").replace("state.json", "global-history.jsonl") in caplog.text


def test_explicit_history_override_is_passed_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []

    def run(config, state, artifacts, **kwargs):
        calls.append((config, state, artifacts, kwargs))
        return SimpleNamespace(
            state=SimpleNamespace(revision=1, snapshot=SimpleNamespace(display_date=date(2026, 1, 1))),
            selected_initial_quotation=True,
            presented_stage=0,
        )

    monkeypatch.setattr(cli, "run_startup", run)
    assert cli.main(["--once", "--history", "custom-history.jsonl"]) == 0
    assert calls[0][3]["history_path"] == "custom-history.jsonl"


def test_demo_uses_default_configuration_and_never_receives_production_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main(["--demo", "5"]) == 0
    assert calls[0][0] == (paths.config_file, 5.0)
    assert not {"state_path", "artifact_root", "history_path"}.intersection(calls[0][1])


def test_missing_configuration_is_actionable_and_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("must not start"))

    assert cli.main([]) == 1
    diagnostic = capsys.readouterr().err
    assert str(paths.config_file) in diagnostic
    assert "python -m refrain --initialize" in diagnostic
    assert not paths.config_directory.exists()


def test_explicit_missing_configuration_does_not_fall_back_to_installed_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("must not start"))

    assert cli.main(["--config", str(missing)]) == 1
    diagnostic = capsys.readouterr().err
    assert str(missing) in diagnostic
    assert paths.config_file.is_file()


@pytest.mark.parametrize(
    "operation,override",
    [
        ("--initialize", ["--config", "custom.yaml"]),
        ("--initialize", ["--state", "state.json"]),
        ("--initialize", ["--artifacts", "images"]),
        ("--initialize", ["--history", "history.jsonl"]),
        ("--reset", ["--config", "custom.yaml"]),
        ("--reset", ["--state", "state.json"]),
        ("--reset", ["--artifacts", "images"]),
        ("--reset", ["--history", "history.jsonl"]),
        ("--purge", ["--config", "custom.yaml"]),
        ("--purge", ["--state", "state.json"]),
        ("--purge", ["--artifacts", "images"]),
        ("--purge", ["--history", "history.jsonl"]),
    ],
)
def test_administrative_operations_reject_all_path_overrides(
    operation: str, override: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main([operation, *override])
    assert error.value.code == 2
    assert "cannot be combined with path overrides" in capsys.readouterr().err


@pytest.mark.parametrize("mode", [["--once"], ["--demo", "5"]])
@pytest.mark.parametrize("operation", ["--initialize", "--reset", "--purge"])
def test_administrative_operations_are_mutually_exclusive_with_runtime_modes(
    operation: str, mode: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main([operation, *mode])
    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_initialize_cli_exits_without_starting_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("normal lifecycle started"))
    monkeypatch.setattr(cli, "run_startup", lambda *args, **kwargs: pytest.fail("normal lifecycle started"))
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("demo lifecycle started"))

    assert cli.main(["--initialize"]) == 0
    output = capsys.readouterr().out
    assert "Initialization complete." in output
    assert str(paths.config_file) in output
    assert str(paths.content_directory) in output
    assert str(paths.state_directory) in output
    assert str(paths.artifacts_directory) in output


@pytest.mark.parametrize("operation", ["--reset", "--purge"])
def test_destructive_cli_operations_require_confirmation_before_work(
    operation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.config_file.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "confirm_operation", lambda *args, **kwargs: False)
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("normal lifecycle started"))
    monkeypatch.setattr(cli, "run_startup", lambda *args, **kwargs: pytest.fail("normal lifecycle started"))
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("demo lifecycle started"))
    monkeypatch.setattr(cli, "reset_installation", lambda *args: pytest.fail("reset ran before confirmation"))
    monkeypatch.setattr(cli, "purge_installation", lambda *args: pytest.fail("purge ran before confirmation"))

    assert cli.main([operation]) == 1
    assert paths.config_file.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    "operation,method",
    [("--reset", "reset_installation"), ("--purge", "purge_installation")],
)
def test_destructive_cli_operations_exit_without_starting_application(
    operation: str,
    method: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "confirm_operation", lambda *args, **kwargs: True)
    calls = []
    monkeypatch.setattr(
        cli,
        method,
        lambda *args: calls.append(args) or (() if method == "purge_installation" else None),
    )
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("normal lifecycle started"))
    monkeypatch.setattr(cli, "run_startup", lambda *args, **kwargs: pytest.fail("normal lifecycle started"))
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("demo lifecycle started"))

    assert cli.main([operation]) == 0
    assert calls == [(paths,)]

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread

import pytest

import refrain.__main__ as cli
from refrain.ownership import InstallationOwnership, OwnershipError
from refrain.paths import resolve_application_paths


@pytest.fixture
def user_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    for name, value in {
        "HOME": home,
        "USERPROFILE": home,
        "APPDATA": home / "roaming",
        "LOCALAPPDATA": home / "local",
        "XDG_CONFIG_HOME": home / "config",
        "XDG_STATE_HOME": home / "state",
        "XDG_CACHE_HOME": home / "cache",
    }.items():
        monkeypatch.setenv(name, str(value))
    return os.environ.copy()


def _start_holder(environment: dict[str, str], mode: str, config: Path) -> subprocess.Popen:
    program = """
import sys
import refrain.__main__ as cli
def hold(*args, **kwargs):
    print("READY", flush=True)
    sys.stdin.readline()
cli.run_application = hold
cli.run_demo = hold
raise SystemExit(cli.main(sys.argv[1:]))
"""
    arguments = ["--config", str(config)]
    if mode == "demo":
        arguments += ["--demo", "1"]
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", program, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "READY"
    return process


def _stop_holder(process: subprocess.Popen) -> None:
    stdout, stderr = process.communicate("\n", timeout=10)
    assert process.returncode == 0, (stdout, stderr)


def _config(path: Path, storage: Path) -> Path:
    path.write_text(
        Path(cli.__file__).with_name("config.default.yaml").read_text(encoding="utf-8")
        + f"\nstorage:\n  state: '{(storage / 'state.json').as_posix()}'\n"
        + f"  history: '{(storage / 'history.jsonl').as_posix()}'\n"
        + f"  artifacts: '{(storage / 'artifacts').as_posix()}'\n",
        encoding="utf-8",
    )
    return path


def test_cross_process_exclusion_and_crash_recovery(user_environment: dict[str, str], tmp_path: Path) -> None:
    path = Path.home() / ".refrain-ownership.lock"
    path.write_text("stale metadata is not ownership", encoding="utf-8")
    owner = InstallationOwnership(path)
    owner.acquire()
    with pytest.raises(OwnershipError, match="another Refrain"):
        InstallationOwnership(path).acquire()
    probe = "from refrain.ownership import InstallationOwnership; InstallationOwnership().acquire()"
    result = subprocess.run([sys.executable, "-c", probe], env=user_environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "another Refrain" in result.stderr
    owner.release()
    owner.release()
    result = subprocess.run([sys.executable, "-c", probe], env=user_environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    program = (
        "from refrain.ownership import InstallationOwnership; "
        "import sys; lock = InstallationOwnership(); lock.acquire(); "
        "print('READY', flush=True); sys.stdin.readline()"
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", program],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=user_environment,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        with pytest.raises(OwnershipError, match="another Refrain"):
            InstallationOwnership(path).acquire()
    finally:
        process.kill()
        process.communicate(timeout=10)
    with InstallationOwnership(path):
        assert path.exists()


@pytest.mark.parametrize("holder", ["normal", "demo"])
@pytest.mark.parametrize("contender", ["normal", "demo"])
def test_runtime_and_demo_contend_across_processes(
    holder: str,
    contender: str,
    user_environment: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _config(tmp_path / "first.yaml", tmp_path / "first-storage")
    second = _config(tmp_path / "second.yaml", tmp_path / "second-storage")
    process = _start_holder(user_environment, holder, first)
    calls = []
    monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: calls.append("normal"))
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: calls.append("demo"))
    arguments = ["--config", str(second)] + (["--demo", "1"] if contender == "demo" else [])
    try:
        assert cli.main(arguments) == 1
        assert "another Refrain" in capsys.readouterr().err
        assert not calls
        assert not (tmp_path / "first-storage").exists()
        assert not (tmp_path / "second-storage").exists()
    finally:
        _stop_holder(process)
    assert cli.main(arguments) == 0
    assert calls == [contender]


@pytest.mark.parametrize("operation", ["--initialize", "--reset", "--purge"])
def test_installation_commands_fail_without_mutation_until_owner_exits(
    operation: str,
    user_environment: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = resolve_application_paths()
    config = _config(tmp_path / "runtime.yaml", tmp_path / "custom")
    if operation != "--initialize":
        for path in (paths.config_file, paths.state_file, paths.history_file, paths.artifacts_directory / "image"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(cli, "confirm_operation", lambda *args, **kwargs: True)
    process = _start_holder(user_environment, "normal", config)
    try:
        assert cli.main([operation]) == 1
        assert "another Refrain" in capsys.readouterr().err
        if operation == "--initialize":
            assert not Path(paths.config_directory).exists()
            assert not Path(paths.operational_directory).exists()
            assert not Path(paths.cache_directory).exists()
        else:
            for path in (paths.config_file, paths.state_file, paths.history_file, paths.artifacts_directory / "image"):
                assert Path(path).read_text(encoding="utf-8") == "preserve"
    finally:
        _stop_holder(process)
    assert cli.main([operation]) == 0
    if operation == "--initialize":
        assert Path(paths.config_file).is_file()
    elif operation == "--reset":
        assert Path(paths.config_file).is_file()
        assert not Path(paths.state_file).exists()
        assert not Path(paths.history_file).exists()
        assert not Path(paths.artifacts_directory / "image").exists()
    else:
        assert not Path(paths.config_directory).exists()
        assert not Path(paths.operational_directory).exists()
        assert not Path(paths.cache_directory).exists()
    assert (Path.home() / ".refrain-ownership.lock").exists()


def test_ownership_remains_held_until_pending_backend_worker_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "lock"
    started, stop, cleaned, backend_closed = Event(), Event(), Event(), Event()
    worker = Thread(target=lambda: (started.set(), stop.wait()))
    worker.start()
    assert started.wait(1)
    try:
        with InstallationOwnership(path) as ownership:
            original_release = ownership.release

            def release():
                assert backend_closed.is_set()
                original_release()
                cleaned.set()

            monkeypatch.setattr(ownership, "release", release)
            ownership.defer_release_until((worker,), backend_closed.set)
        with pytest.raises(OwnershipError, match="another Refrain"):
            InstallationOwnership(path).acquire()
    finally:
        stop.set()
        worker.join(timeout=5)
    assert cleaned.wait(5)
    with InstallationOwnership(path):
        pass


def test_refuses_lock_inside_installation_tree(tmp_path: Path) -> None:
    ownership = InstallationOwnership(tmp_path / "refrain" / "lock")
    with pytest.raises(OwnershipError, match="inside a standard installation"):
        ownership.ensure_outside((tmp_path / "refrain",))


@pytest.mark.parametrize("mode", ["normal", "demo"])
def test_failed_runtime_releases_ownership(
    mode: str, user_environment: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "config.yaml", tmp_path / "custom")
    monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)

    def fail(*args, **kwargs):
        raise cli.ApplicationError("injected failure")

    monkeypatch.setattr(cli, "run_application", fail)
    monkeypatch.setattr(cli, "run_demo", fail)
    arguments = ["--config", str(config)] + (["--demo", "1"] if mode == "demo" else [])
    assert cli.main(arguments) == 1
    with InstallationOwnership():
        pass


def test_open_failure_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(OwnershipError, match="cannot open Refrain ownership lock"):
        InstallationOwnership(tmp_path / "missing" / "lock").acquire()

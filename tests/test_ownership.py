from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread

import pytest

import refrain.__main__ as cli
import refrain.ownership as ownership_module
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
    path = Path(resolve_application_paths().ownership_file)
    path.parent.mkdir(parents=True)
    path.write_text("stale metadata is not ownership", encoding="utf-8")
    owner = InstallationOwnership(path)
    owner.acquire()
    with pytest.raises(OwnershipError, match="Refrain is already running"):
        InstallationOwnership(path).acquire()
    probe = (
        "from pathlib import Path; from refrain.paths import resolve_application_paths; "
        "from refrain.ownership import InstallationOwnership; "
        "InstallationOwnership(Path(resolve_application_paths().ownership_file)).acquire()"
    )
    result = subprocess.run([sys.executable, "-c", probe], env=user_environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Refrain is already running" in result.stderr
    owner.release()
    owner.release()
    result = subprocess.run([sys.executable, "-c", probe], env=user_environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    program = (
        "from pathlib import Path; from refrain.paths import resolve_application_paths; "
        "from refrain.ownership import InstallationOwnership; "
        "import sys; lock = InstallationOwnership(Path(resolve_application_paths().ownership_file)); lock.acquire(); "
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
        with pytest.raises(OwnershipError, match="Refrain is already running"):
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
    holder_environment = user_environment.copy()
    holder_environment["HOME"] = str(tmp_path / "other-home")
    holder_environment["USERPROFILE"] = str(tmp_path / "other-profile")
    process = _start_holder(holder_environment, holder, first)
    calls = []
    monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: calls.append("normal"))
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: calls.append("demo"))
    arguments = ["--config", str(second)] + (["--demo", "1"] if contender == "demo" else [])
    try:
        with monkeypatch.context() as patch:
            patch.setattr(cli, "load_application_config", lambda *args: pytest.fail("configuration opened"))
            assert cli.main(arguments) == 1
        assert "Refrain is already running or another Refrain operation is in progress; stop it and retry." in (
            capsys.readouterr().err
        )
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
        assert "Refrain is already running" in capsys.readouterr().err
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
    assert Path(paths.ownership_file).exists()


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
        with pytest.raises(OwnershipError, match="Refrain is already running"):
            InstallationOwnership(path).acquire()
    finally:
        stop.set()
        worker.join(timeout=5)
    assert cleaned.wait(5)
    with InstallationOwnership(path):
        pass


def test_refuses_lock_inside_installation_tree(tmp_path: Path) -> None:
    ownership = InstallationOwnership(tmp_path / "refrain" / "lock")
    with pytest.raises(OwnershipError, match="inside a managed path"):
        ownership.ensure_outside((tmp_path / "refrain",))


def test_existing_standard_bases_do_not_require_a_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("XDG base directory behavior applies to Linux")
    for variable, directory in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / directory))
    monkeypatch.setenv("HOME", str(tmp_path / "missing-home"))
    assert cli.main(["--initialize"]) == 0, capsys.readouterr().err
    paths = resolve_application_paths()
    assert Path(paths.config_file).is_file()
    assert Path(paths.ownership_file).is_file()
    assert not (tmp_path / "missing-home").exists()


def test_conflicting_standard_paths_are_rejected_before_lock_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("XDG base directory behavior applies to Linux")
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(config / "refrain" / "nested"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert cli.main(["--initialize"]) == 1
    assert "inside a managed path" in capsys.readouterr().err
    assert not config.exists()


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
    with InstallationOwnership(Path(resolve_application_paths().ownership_file)):
        pass


@pytest.mark.parametrize("storage", ["state", "history", "artifacts"])
def test_runtime_rejects_storage_that_can_replace_ownership_lock(
    storage: str,
    user_environment: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = Path(resolve_application_paths().ownership_file)
    destination = lock.parent if storage == "artifacts" else lock
    config = tmp_path / "config.yaml"
    config.write_text(
        Path(cli.__file__).with_name("config.default.yaml").read_text(encoding="utf-8")
        + f"\nstorage:\n  {storage}: '{destination.as_posix()}'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("runtime started"))
    assert cli.main(["--config", str(config)]) == 1
    assert "ownership lock" in capsys.readouterr().err
    with InstallationOwnership(lock):
        pass


def test_open_failure_is_actionable(tmp_path: Path) -> None:
    parent = tmp_path / "not-a-directory"
    parent.write_text("file", encoding="utf-8")
    with pytest.raises(OwnershipError, match="cannot open Refrain ownership lock"):
        InstallationOwnership(parent / "lock").acquire()


def test_release_failure_is_actionable_and_closes_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = InstallationOwnership(tmp_path / "lock")
    owner.acquire()
    platform_locks = ownership_module.msvcrt if os.name == "nt" else ownership_module.fcntl
    lock_function = "locking" if os.name == "nt" else "flock"

    def fail(*args):
        raise OSError("injected unlock failure")

    with monkeypatch.context() as patch:
        patch.setattr(platform_locks, lock_function, fail)
        with pytest.raises(OwnershipError, match="cannot release Refrain ownership lock"):
            owner.release()
    owner.release()
    with InstallationOwnership(owner.path):
        pass


@pytest.mark.parametrize("mode", ["normal", "demo"])
def test_real_lifecycle_holds_lock_until_fake_backend_is_closed(
    mode: str,
    user_environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--initialize"]) == 0
    config = Path(resolve_application_paths().config_file)
    program = """
import sys
from threading import Thread
import refrain.__main__ as cli

class Backend:
    def update_output(self, output_id, image):
        print("READY", flush=True)
    def publish(self, destination, image):
        self.update_output(destination.identifier, image)
    def close(self):
        print("CLOSING", flush=True)
        sys.stdin.readline()
        print("CLOSED", flush=True)

def wrap(run):
    def start(*args, **kwargs):
        shutdown = kwargs["shutdown_event"]
        Thread(target=lambda: (sys.stdin.readline(), shutdown.set()), daemon=True).start()
        return run(*args, backend_factory=lambda configuration: Backend(), **kwargs)
    return start

cli.run_application = wrap(cli.run_application)
cli.run_demo = wrap(cli.run_demo)
raise SystemExit(cli.main(sys.argv[1:]))
"""
    arguments = ["--config", str(config)] + (["--demo", "1"] if mode == "demo" else [])
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", program, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=user_environment,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)
        monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("backend opened"))
        monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("backend opened"))
        assert cli.main(arguments) == 1
        assert "Refrain is already running" in capsys.readouterr().err
        assert process.stdin is not None
        process.stdin.write("shutdown\n")
        process.stdin.flush()
        assert process.stdout.readline().strip() == "CLOSING"
        assert cli.main(arguments) == 1
        assert "Refrain is already running" in capsys.readouterr().err
    finally:
        stdout, stderr = process.communicate("\n", timeout=30)
    assert process.returncode == 0, (stdout, stderr)
    assert "CLOSED" in stdout
    with InstallationOwnership(Path(resolve_application_paths().ownership_file)):
        pass

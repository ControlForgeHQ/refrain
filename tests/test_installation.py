from __future__ import annotations

import io
import signal
from pathlib import Path, PureWindowsPath

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
    assert actual.ownership_file == home / ".local/state/.refrain-ownership.lock"


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
    assert paths.ownership_file == state / ".refrain-ownership.lock"


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
    assert str(paths.ownership_file) == r"C:\Users\Ada\AppData\Local\.refrain-ownership.lock"


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
    assert paths.ownership_file == home / "Library/Application Support/.refrain-ownership.lock"


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
    assert config.default_fonts == ("alegreya", "libre-baskerville", "lora", "source-sans-3")
    assert config.default_backgrounds == (
        "none",
        "aged-paper",
        "canvas",
        "cloth",
        "drafting-grid",
        "handmade-paper",
        "hex",
        "isometric-grid",
        "limestone",
        "recursive-squares",
        "vellum",
    )
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
    assert paths.assets_directory.is_dir()
    assert all((paths.assets_directory / category).is_dir() for category in ("fonts", "backgrounds", "decorations"))
    assert not paths.state_file.exists()
    assert not paths.history_file.exists()
    assert any("Configuration:" in message for message in reports)
    assert any("Content:" in message for message in reports)
    assert any("State directory:" in message for message in reports)
    assert any("Artifacts:" in message for message in reports)
    assert paths.state_directory in created
    assert paths.artifacts_directory in created


def test_initialization_preserves_nonempty_assets_and_does_not_validate_them(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    user_asset = paths.assets_directory / "fonts" / "nested" / "user-font.ttf"
    user_asset.parent.mkdir(parents=True)
    user_asset.write_bytes(b"not a font, initialization does not validate assets")
    (paths.assets_directory / "backgrounds").mkdir()

    initialize_installation(paths)
    contents = {
        path.relative_to(paths.assets_directory): path.read_bytes()
        for path in paths.assets_directory.rglob("*")
        if path.is_file()
    }
    initialize_installation(paths)

    assert {
        path.relative_to(paths.assets_directory): path.read_bytes()
        for path in paths.assets_directory.rglob("*")
        if path.is_file()
    } == contents
    assert user_asset.read_bytes() == b"not a font, initialization does not validate assets"
    assert (paths.assets_directory / "decorations").is_dir()


@pytest.mark.parametrize("category", ["assets", "assets/fonts", "assets/backgrounds", "assets/decorations"])
def test_initialization_rejects_files_blocking_asset_directories_before_writing(tmp_path: Path, category: str) -> None:
    paths = _paths(tmp_path)
    blocker = paths.config_directory / category
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_bytes(b"user data")

    with pytest.raises(InitializationError) as error:
        initialize_installation(paths)

    assert str(blocker) in str(error.value)
    assert blocker.read_bytes() == b"user data"
    assert not paths.config_file.exists()


def test_initialization_rejects_linked_asset_directory_without_following_it(tmp_path: Path, symlink_or_skip) -> None:
    paths = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep"
    sentinel.write_bytes(b"outside")
    paths.assets_directory.mkdir(parents=True)
    symlink_or_skip(paths.assets_directory / "fonts", external, directory=True)

    with pytest.raises(InitializationError, match="filesystem link"):
        initialize_installation(paths)

    assert sentinel.read_bytes() == b"outside"
    assert not paths.config_file.exists()


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


def test_preflight_rejects_unexpected_objects_before_writing(tmp_path: Path, symlink_or_skip) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.config_file.mkdir()
    paths.content_directory.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(paths.content_directory, tmp_path / "elsewhere", directory=True)

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


def test_symlink_destination_is_a_conflict(tmp_path: Path, symlink_or_skip) -> None:
    paths = _paths(tmp_path)
    paths.cache_directory.parent.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    symlink_or_skip(paths.cache_directory, unrelated, directory=True)

    with pytest.raises(InitializationError) as error:
        initialize_installation(paths)

    assert str(paths.cache_directory) in str(error.value)
    assert list(unrelated.iterdir()) == []
    assert not paths.config_directory.exists()


def test_symlink_helper_does_not_skip_unrelated_creation_errors(tmp_path: Path, symlink_or_skip) -> None:
    link = tmp_path / "existing-link"
    link.write_text("not a link", encoding="utf-8")

    with pytest.raises(FileExistsError):
        symlink_or_skip(link, tmp_path / "target")


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


def test_partial_sample_installation_is_detected_and_completed_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    shared_data = paths.config_directory.parent / "other-user-file.txt"
    shared_data.parent.mkdir(parents=True)
    shared_data.write_text("preserve", encoding="utf-8")
    original_create_file = installation._create_file

    sample_writes = 0

    def fail_after_one_sample(path: Path, contents: bytes, created: list[Path], owned_directories: set[Path]) -> None:
        nonlocal sample_writes
        if path.parent == paths.content_directory and path.name != installation._SAMPLE_INSTALL_MARKER:
            sample_writes += 1
            if sample_writes == 2:
                raise OSError("disk full")
        original_create_file(path, contents, created, owned_directories)

    monkeypatch.setattr(installation, "_create_file", fail_after_one_sample)
    with pytest.raises(InitializationError, match="Created destinations that remain in place") as error:
        initialize_installation(paths)
    installed_samples = [path for path in paths.content_directory.glob("*.yaml") if path.is_file()]
    assert len(installed_samples) == 1
    assert installation._SAMPLE_INSTALL_MARKER in {path.name for path in paths.content_directory.iterdir()}
    assert paths.config_file.is_file()
    assert str(paths.config_file) in str(error.value)
    assert paths.content_directory.is_dir()
    assert shared_data.read_text(encoding="utf-8") == "preserve"

    monkeypatch.setattr(installation, "_create_file", original_create_file)
    initialize_installation(paths)

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
    assert installation._SAMPLE_INSTALL_MARKER not in {path.name for path in paths.content_directory.iterdir()}
    assert shared_data.read_text(encoding="utf-8") == "preserve"


def test_arbitrary_nonempty_content_directory_is_not_treated_as_partial_install(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    paths.content_directory.mkdir(parents=True)
    user_file = paths.content_directory / "custom.yaml"
    user_file.write_text("user content", encoding="utf-8")
    before = user_file.read_bytes()

    reports: list[str] = []
    initialize_installation(paths, progress=reports.append)

    assert user_file.read_bytes() == before
    assert not (paths.content_directory / installation._SAMPLE_INSTALL_MARKER).exists()
    assert any("nonempty content directory preserved" in message for message in reports)


def test_invalid_sample_install_marker_requires_manual_intervention(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.content_directory.mkdir(parents=True)
    marker = paths.content_directory / installation._SAMPLE_INSTALL_MARKER
    marker.write_text("not a valid install marker", encoding="utf-8")

    with pytest.raises(InitializationError, match="inspect the files manually"):
        initialize_installation(paths)

    assert marker.read_text(encoding="utf-8") == "not a valid install marker"
    assert not paths.config_file.exists()


def test_partial_initialization_failure_reports_created_data_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    user_asset = paths.assets_directory / "fonts" / "keep.ttf"
    user_asset.parent.mkdir(parents=True)
    user_asset.write_bytes(b"user font")
    original_create_file = installation._create_file

    def fail_on_config(path: Path, contents: bytes, created: list[Path], owned_directories: set[Path]) -> None:
        if path == paths.config_file:
            raise OSError("disk full")
        original_create_file(path, contents, created, owned_directories)

    monkeypatch.setattr(installation, "_create_file", fail_on_config)
    with pytest.raises(InitializationError, match="Created destinations that remain in place") as error:
        initialize_installation(paths)
    assert str(paths.config_file) not in str(error.value)
    assert paths.content_directory.is_dir()
    assert user_asset.read_bytes() == b"user font"


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
    expected_path = Path("/standard/state.json")

    confirmed = confirm_operation(
        "RESET",
        "Reset explanation",
        (expected_path,),
        input_stream=_TerminalInput(response),
        output_stream=output,
    )

    assert confirmed is expected
    assert str(expected_path) in output.getvalue()
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
    asset_files = {
        paths.assets_directory / "fonts" / "nested" / "custom.ttf": b"font bytes",
        paths.assets_directory / "backgrounds" / "paper" / "custom.png": b"background bytes",
        paths.assets_directory / "decorations" / "custom.png": b"decoration bytes",
    }
    for path, contents in asset_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
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
    assert {path: path.read_bytes() for path in asset_files} == asset_files
    assert not paths.state_file.exists()
    assert not paths.history_file.exists()
    assert not (paths.state_directory / "global-history.1.jsonl").exists()
    assert list(paths.artifacts_directory.iterdir()) == []
    assert not (paths.cache_directory / "generated.tmp").exists()
    assert paths.state_directory.is_dir()
    assert paths.artifacts_directory.is_dir()


def test_reset_is_idempotent_and_does_not_follow_artifact_links(tmp_path: Path, symlink_or_skip) -> None:
    paths = _paths(tmp_path)
    paths.artifacts_directory.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("outside", encoding="utf-8")
    symlink_or_skip(paths.artifacts_directory / "linked", external, directory=True)

    reset_installation(paths)
    reset_installation(paths)

    assert list(paths.artifacts_directory.iterdir()) == []
    assert (external / "keep").read_text(encoding="utf-8") == "outside"


def test_reset_rejects_linked_standard_runtime_root(tmp_path: Path, symlink_or_skip) -> None:
    paths = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    paths.artifacts_directory.parent.mkdir(parents=True)
    symlink_or_skip(paths.artifacts_directory, external, directory=True)

    with pytest.raises(InstallationOperationError, match="filesystem link"):
        reset_installation(paths)
    assert not paths.state_directory.exists()
    assert list(external.iterdir()) == []


def test_purge_removes_owned_roots_but_preserves_shared_parents_and_external_links(
    tmp_path: Path, symlink_or_skip
) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    paths.state_directory.mkdir(parents=True)
    paths.cache_directory.mkdir(parents=True)
    external_resource = tmp_path / "external-font.ttf"
    external_resource.write_bytes(b"external font")
    (paths.config_directory / "config.yaml").write_text(
        f"content: {{directory: /external}}\nlayout: {{fonts: {{available: {{outside: {external_resource}}}}}}}\n",
        encoding="utf-8",
    )
    (paths.config_directory / "content").mkdir()
    (paths.config_directory / "content" / "entry.yaml").write_text("user content", encoding="utf-8")
    assets = {
        paths.assets_directory / "fonts" / "serif" / "custom.ttf": b"custom font",
        paths.assets_directory / "backgrounds" / "paper" / "custom.png": b"custom background",
        paths.assets_directory / "decorations" / "frames" / "custom.png": b"custom decoration",
    }
    for path, contents in assets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("outside", encoding="utf-8")
    symlink_or_skip(paths.config_directory / "linked", external, directory=True)

    removed = purge_installation(paths)

    assert set(removed) == {paths.config_directory, paths.state_directory, paths.cache_directory}
    assert not paths.config_directory.exists()
    assert not paths.state_directory.exists()
    assert not paths.cache_directory.exists()
    assert not paths.assets_directory.exists()
    assert paths.config_directory.parent.is_dir()
    assert paths.state_directory.parent.is_dir()
    assert paths.cache_directory.parent.is_dir()
    assert (external / "keep").read_text(encoding="utf-8") == "outside"
    assert not any(path.exists() for path in assets)
    assert external_resource.read_bytes() == b"external font"
    assert purge_installation(paths) == removed


def test_purge_refuses_linked_installation_root(tmp_path: Path, symlink_or_skip) -> None:
    paths = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("outside", encoding="utf-8")
    paths.config_directory.parent.mkdir(parents=True)
    symlink_or_skip(paths.config_directory, external, directory=True)

    with pytest.raises(InstallationOperationError, match="filesystem link"):
        purge_installation(paths)

    assert (external / "keep").read_text(encoding="utf-8") == "outside"


def test_purge_removes_nested_junction_without_following_external_target(tmp_path: Path, junction_or_skip) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep"
    sentinel.write_text("outside", encoding="utf-8")
    junction = paths.config_directory / "linked"
    junction_or_skip(junction, external)

    purge_installation(paths)

    assert not paths.config_directory.exists()
    assert not junction.is_junction()
    assert sentinel.read_text(encoding="utf-8") == "outside"


def test_purge_refuses_standard_installation_junction_root(tmp_path: Path, junction_or_skip) -> None:
    paths = _paths(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep"
    sentinel.write_text("outside", encoding="utf-8")
    paths.config_directory.parent.mkdir(parents=True)
    junction_or_skip(paths.config_directory, external)

    with pytest.raises(InstallationOperationError, match="filesystem link"):
        purge_installation(paths)

    assert paths.config_directory.is_junction()
    assert sentinel.read_text(encoding="utf-8") == "outside"


def test_reset_removes_artifact_junction_without_following_external_target(tmp_path: Path, junction_or_skip) -> None:
    paths = _paths(tmp_path)
    paths.artifacts_directory.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep"
    sentinel.write_text("outside", encoding="utf-8")
    junction = paths.artifacts_directory / "linked"
    junction_or_skip(junction, external)

    reset_installation(paths)

    assert list(paths.artifacts_directory.iterdir()) == []
    assert not junction.is_junction()
    assert sentinel.read_text(encoding="utf-8") == "outside"


def _install_cli_paths(monkeypatch: pytest.MonkeyPatch, paths: ApplicationPaths) -> None:
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    paths.config_directory.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text(Path(cli.__file__).with_name("config.default.yaml").read_text(encoding="utf-8"))
    monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)


def test_default_cli_paths_work_without_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []

    def run(config, state, artifacts, **kwargs):
        calls.append((config, state, artifacts, kwargs))

    monkeypatch.setattr(cli, "run_application", run)
    assert cli.main([]) == 0
    configuration, state_path, artifacts_path, kwargs = calls[0]
    assert configuration.file == paths.config_file.absolute()
    assert (state_path, artifacts_path) == (paths.state_file, paths.artifacts_directory)
    assert kwargs["history_path"] == paths.history_file


def test_alternate_config_does_not_relocate_omitted_storage_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []

    def run(config, state, artifacts, **kwargs):
        calls.append((config, state, artifacts, kwargs))

    monkeypatch.setattr(cli, "run_application", run)
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(Path(cli.__file__).with_name("config.default.yaml").read_text(encoding="utf-8"))
    assert cli.main(["--config", str(config_path)]) == 0
    configuration, state_path, artifacts_path, kwargs = calls[0]
    assert configuration.file == config_path.absolute()
    assert (state_path, artifacts_path) == (paths.state_file, paths.artifacts_directory)
    assert kwargs["history_path"] == paths.history_file
    assert str(paths.history_file) in caplog.text


def test_custom_state_path_does_not_relocate_omitted_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(cli, "run_application", run)
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(
        Path(cli.__file__).with_name("config.default.yaml").read_text(encoding="utf-8")
        + "\nstorage:\n  state: ./custom-state.json\n",
        encoding="utf-8",
    )

    assert cli.main(["--config", str(config_path)]) == 0

    assert calls[0][0][1] == config_path.parent / "custom-state.json"
    assert calls[0][1]["history_path"] == paths.history_file
    assert calls[0][1]["history_path"] != calls[0][0][1].with_name("global-history.jsonl")


def test_storage_configuration_overrides_each_runtime_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []

    def run(config, state, artifacts, **kwargs):
        calls.append((config, state, artifacts, kwargs))

    monkeypatch.setattr(cli, "run_application", run)
    config_path = tmp_path / "alternate" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        Path(cli.__file__).with_name("config.default.yaml").read_text(encoding="utf-8")
        + (
            "\nstorage:\n"
            "  state: ./runtime/state.json\n"
            "  history: ./runtime/history.jsonl\n"
            "  artifacts: ./runtime/artifacts\n"
        ),
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config_path)]) == 0
    configuration, state_path, artifacts_path, kwargs = calls[0]
    assert configuration.file == config_path
    assert state_path == config_path.parent / "runtime/state.json"
    assert kwargs["history_path"] == config_path.parent / "runtime/history.jsonl"
    assert artifacts_path == config_path.parent / "runtime/artifacts"


def test_demo_uses_default_configuration_and_never_receives_production_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _install_cli_paths(monkeypatch, paths)
    calls = []
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert cli.main(["--demo", "5"]) == 0
    assert calls[0][0] == (paths.config_file, 5.0)
    assert set(calls[0][1]) == {"shutdown_event", "pending_shutdown"}


def test_missing_configuration_is_actionable_and_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "run_application", lambda *args, **kwargs: pytest.fail("must not start"))

    assert cli.main([]) == 1
    diagnostic = capsys.readouterr().err
    assert str(paths.config_file) in diagnostic
    assert "refrain --initialize" in diagnostic
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
    "option",
    ["--state", "--artifacts", "--history", "--history-segment-size", "--history-max-segments"],
)
def test_removed_storage_options_are_rejected(option: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main([option, "value"])

    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--show-entry", "entry"],
        ["--test-decoration", "all"],
        ["--test-output", "preview.png"],
        ["--test-variants", "previews"],
        ["--test-aspect", "4:3"],
        ["--test-resolution", "1600", "1200"],
        ["--test-quotation", "short"],
        ["--no-qr"],
        ["--no-background"],
        ["--no-tinting"],
        ["--once"],
        ["--debug-layout"],
    ],
)
def test_legacy_presentation_options_are_rejected(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_main_help_omits_legacy_presentation_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--demo" in output
    for option in (
        "--show-entry",
        "--test-decoration",
        "--test-output",
        "--test-variants",
        "--test-aspect",
        "--test-resolution",
        "--test-quotation",
        "--no-qr",
        "--no-background",
        "--no-tinting",
        "--once",
        "--debug-layout",
    ):
        assert option not in output


@pytest.mark.parametrize("operation", ["--initialize", "--reset", "--purge"])
def test_installation_operations_ignore_configured_storage_paths(
    operation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.config_directory.mkdir(parents=True)
    custom_storage = tmp_path / "custom-storage"
    custom_files = [
        custom_storage / "state.json",
        custom_storage / "global-history.jsonl",
        custom_storage / "artifacts" / "prepared.png",
    ]
    for path in custom_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("custom data", encoding="utf-8")
    paths.config_file.write_text(
        "storage:\n"
        f"  state: {custom_files[0]}\n"
        f"  history: {custom_files[1]}\n"
        f"  artifacts: {custom_files[2].parent}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "confirm_operation", lambda *args, **kwargs: True)

    assert cli.main([operation]) == 0

    assert [path.read_text(encoding="utf-8") for path in custom_files] == ["custom data"] * 3


@pytest.mark.parametrize("operation", ["--initialize", "--reset", "--purge"])
def test_administrative_operations_reject_alternate_configuration(
    operation: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main([operation, "--config", "custom.yaml"])
    assert error.value.code == 2
    assert "cannot be combined with --config" in capsys.readouterr().err


@pytest.mark.parametrize("mode", [["--demo", "5"]])
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
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("demo lifecycle started"))

    assert cli.main(["--initialize"]) == 0
    output = capsys.readouterr().out
    assert "Initialization complete." in output
    assert str(paths.config_file) in output
    assert str(paths.content_directory) in output
    assert str(paths.assets_directory) in output
    assert str(paths.assets_directory / "fonts") in output
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
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("demo lifecycle started"))
    monkeypatch.setattr(cli, "reset_installation", lambda *args: pytest.fail("reset ran before confirmation"))
    monkeypatch.setattr(cli, "purge_installation", lambda *args: pytest.fail("purge ran before confirmation"))

    assert cli.main([operation]) == 1
    assert paths.config_file.read_text(encoding="utf-8") == "preserve"


def test_cancelled_purge_preserves_assets_and_describes_their_deletion_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    custom_asset = paths.assets_directory / "fonts" / "custom.ttf"
    custom_asset.parent.mkdir(parents=True)
    custom_asset.write_bytes(b"custom font")
    captured: dict[str, object] = {}

    def cancel(confirmation: str, description: str, locations: tuple[Path, ...]) -> bool:
        captured.update(confirmation=confirmation, description=description, locations=locations)
        return False

    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli, "confirm_operation", cancel)

    assert cli.main(["--purge"]) == 1

    assert captured["confirmation"] == "PURGE REFRAIN"
    assert "custom fonts, backgrounds, and decorations" in captured["description"]
    assert paths.assets_directory in captured["locations"]
    assert custom_asset.read_bytes() == b"custom font"


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
    monkeypatch.setattr(cli, "run_demo", lambda *args, **kwargs: pytest.fail("demo lifecycle started"))

    assert cli.main([operation]) == 0
    assert calls == [(paths,)]

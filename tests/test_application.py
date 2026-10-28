from __future__ import annotations

import logging
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path
from random import Random
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

import refrain.application as application
from refrain import (
    ApplicationError,
    NoEligibleQuotationError,
    PersistentStateStore,
    StateCommitError,
    run_startup,
)
from refrain.__main__ import main
from refrain.display import (
    DisplayBackendCloseError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
)

_ZONE = ZoneInfo("America/Toronto")
_LORA = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf").read_bytes()

_CONFIG = """\
general:
  timezone: "America/Toronto"
  day_start: "06:00"
content:
  directory: "content"
reveal:
  source: "12:00"
  attribution: "18:00"
display:
  backend: "waveshare-13in3-e"
layout:
  presentation_region: {x: 0.1, y: 0.15, width: 0.8, height: 0.55}
  fonts:
    default: ["lora"]
  text: {min_font_size: 28, max_font_size: 100}
"""


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=_ZONE)


class FakeDisplay:
    def __init__(self, *, fail_update: bool = False, fail_close: bool = False) -> None:
        self.fail_update = fail_update
        self.fail_close = fail_close
        self.sizes: list[tuple[int, int]] = []
        self.images: list[Image.Image] = []
        self.closed = 0

    def update(self, image: Image.Image) -> None:
        if self.fail_update:
            raise DisplayBackendUpdateError("update failed")
        self.sizes.append(image.size)
        self.images.append(image.copy())

    def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            raise DisplayBackendCloseError("close failed")


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = root / "config.yaml"
        self.content = root / "content"
        self.state = root / "state" / "state.json"
        self.artifacts = root / "artifacts"
        self.config.write_text(_CONFIG, encoding="utf-8")
        self.content.mkdir()

    def entry(self, name: str, body: str) -> None:
        (self.content / f"{name}.yaml").write_text(f'id: "{name}"\n{body}', encoding="utf-8")

    def run(self, now: datetime, display: FakeDisplay | None = None, **kwargs):
        display = display or FakeDisplay()
        result = run_startup(
            self.config,
            self.state,
            self.artifacts,
            now=now,
            random_source=Random(1),
            backend_factory=lambda configuration: display,
            **kwargs,
        )
        return result, display

    def load(self):
        return PersistentStateStore(self.state).load()


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def ordinary(workspace: Workspace, text: str = "An ordinary quotation.", extra: str = "") -> None:
    workspace.entry("ordinary", f'source: "A Book"\nattribution: "An Author"\n{extra}quotations:\n  - "{text}"\n')


def png_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.png"))


def test_first_startup_commits_snapshot_and_presents(workspace: Workspace) -> None:
    ordinary(workspace)
    result, display = workspace.run(at(10, 7))

    state = workspace.load()
    assert result.selected_initial_quotation and result.presented_stage == 0
    assert state is not None and state.revision == 1 and state.highest_reveal_stage == 0
    snapshot = state.snapshot
    assert snapshot.quotation_text == "An ordinary quotation."
    assert snapshot.font.identifier == "lora" and snapshot.font.data == _LORA
    assert snapshot.display_date == date(2026, 3, 10)
    assert snapshot.presentation_metadata == {
        "presentation_style": "centered",
        "source": "A Book",
        "attribution": "An Author",
    }
    assert dict(snapshot.reveal_schedule) == {"quotation": "06:00", "source": "12:00", "attribution": "18:00"}
    assert snapshot.layout["image_size"] == (1600, 1200) or list(snapshot.layout["image_size"]) == [1600, 1200]
    assert state.repetition_history == {snapshot.quotation_identity}
    assert len(state.global_history) == 1
    assert display.sizes == [(1600, 1200)] and display.closed == 1
    assert len(png_files(workspace.artifacts)) == 3


def test_startup_before_day_start_uses_previous_display_date(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 5, 30))
    state = workspace.load()
    assert state.snapshot.display_date == date(2026, 3, 9)


def test_date_specific_entry_takes_precedence(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 10\nquotations:\n  - "A special quotation."\n')
    workspace.run(at(10, 8))
    assert workspace.load().snapshot.quotation_text == "A special quotation."


def test_multiple_quotations_select_one_and_record_history(workspace: Workspace) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n  - "Third."\n')
    workspace.run(at(10, 8))
    state = workspace.load()
    assert state.snapshot.quotation_text in {"First.", "Second.", "Third."}
    assert state.repetition_history == {state.snapshot.quotation_identity}


def test_entry_font_preference_is_resolved(workspace: Workspace) -> None:
    ordinary(workspace, extra='font: "source-sans-3"\n')
    workspace.run(at(10, 8))
    font = workspace.load().snapshot.font
    assert font.identifier == "source-sans-3"
    assert font.data != _LORA


def test_unavailable_font_falls_back_to_default_pool(workspace: Workspace, caplog) -> None:
    ordinary(workspace, extra='font: "missing-font"\n')
    with caplog.at_level(logging.WARNING):
        workspace.run(at(10, 8))
    assert workspace.load().snapshot.font.identifier == "lora"
    assert "missing-font" in caplog.text


def test_reveal_overrides_and_simultaneous_reveals(workspace: Workspace) -> None:
    ordinary(workspace, extra='reveal:\n  source: "10:00"\n  attribution: "10:00"\n')
    result, display = workspace.run(at(10, 10, 30))
    assert dict(workspace.load().snapshot.reveal_schedule) == {
        "quotation": "06:00",
        "source": "10:00",
        "attribution": "10:00",
    }
    assert result.presented_stage == 1
    assert len(png_files(workspace.artifacts)) == 2


def test_attribution_can_reveal_before_source(workspace: Workspace) -> None:
    ordinary(workspace, extra='reveal:\n  attribution: "09:00"\n')
    result, _ = workspace.run(at(10, 9, 30))
    assert result.presented_stage == 1
    assert len(png_files(workspace.artifacts)) == 3


def test_invalid_override_before_day_start_commits_nothing(workspace: Workspace) -> None:
    ordinary(workspace, extra='reveal:\n  source: "05:00"\n')
    with pytest.raises(ApplicationError, match="daily snapshot"):
        workspace.run(at(10, 8))
    assert workspace.load() is None


def test_startup_after_reveal_times_presents_latest_stage(workspace: Workspace) -> None:
    ordinary(workspace)
    result, display = workspace.run(at(10, 19))
    assert result.presented_stage == 2
    assert workspace.load().highest_reveal_stage == 2
    assert workspace.load().revision == 1


def test_repeated_startup_preserves_selection_and_artifacts(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n  - "Third."\n')
    workspace.run(at(10, 8))
    first = workspace.load()
    state_bytes = workspace.state.read_bytes()
    artifact_times = {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)}

    def fail(*args, **kwargs):
        raise AssertionError("valid artifacts must not be regenerated")

    monkeypatch.setattr("refrain.recovery.prepare_daily_images", fail)
    result, display = workspace.run(at(10, 9))
    assert not result.selected_initial_quotation
    assert workspace.load() == first
    assert workspace.state.read_bytes() == state_bytes
    assert {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)} == artifact_times
    assert len(display.sizes) == 1


def test_calendar_mismatch_and_missing_content_do_not_reselect(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    first = workspace.load()
    for path in workspace.content.iterdir():
        path.unlink()
    workspace.content.rmdir()
    result, display = workspace.run(at(14, 9))
    state = workspace.load()
    assert (state.revision, state.snapshot, state.global_history, state.repetition_history) == (
        first.revision,
        first.snapshot,
        first.global_history,
        first.repetition_history,
    )
    assert result.presented_stage == 2
    assert len(display.sizes) == 1


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_artifacts_are_recovered(workspace: Workspace, damage: str) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    first = workspace.load()
    if damage == "missing":
        for path in png_files(workspace.artifacts):
            path.unlink()
    else:
        png_files(workspace.artifacts)[0].write_bytes(b"not a png")
    _, display = workspace.run(at(10, 9))
    assert workspace.load() == first
    assert display.sizes == [(1600, 1200)]
    assert len(png_files(workspace.artifacts)) >= 3


def test_backward_clock_does_not_hide_reached_stage(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 19))
    result, display = workspace.run(at(10, 7))
    assert result.presented_stage == 2
    reference = workspace.run(at(10, 19))[1]
    assert display.images[0].tobytes() == reference.images[0].tobytes()
    result, _ = workspace.run(at(9, 7))
    assert result.presented_stage == 2


def test_no_eligible_content_commits_nothing(workspace: Workspace) -> None:
    workspace.entry("other", 'eligibility:\n  - month: 7\nquotations:\n  - "Summer."\n')
    with pytest.raises(NoEligibleQuotationError):
        workspace.run(at(10, 8))
    assert workspace.load() is None and not workspace.artifacts.exists()


def test_invalid_configuration_and_content_report_errors(workspace: Workspace) -> None:
    ordinary(workspace)
    (workspace.content / "bad.yaml").write_text("id: 5\n", encoding="utf-8")
    with pytest.raises(ApplicationError, match="content library"):
        workspace.run(at(10, 8))
    workspace.config.write_text("display: {backend: nope}\n", encoding="utf-8")
    with pytest.raises(ApplicationError, match="configuration"):
        workspace.run(at(10, 8))
    assert workspace.load() is None


def test_invalid_state_is_reported(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.state.parent.mkdir()
    workspace.state.write_text("garbage", encoding="utf-8")
    with pytest.raises(ApplicationError, match="persistent state"):
        workspace.run(at(10, 8))
    assert workspace.state.read_text(encoding="utf-8") == "garbage"


def test_naive_timestamp_is_rejected(workspace: Workspace) -> None:
    ordinary(workspace)
    with pytest.raises(ApplicationError, match="scheduling"):
        workspace.run(datetime(2026, 3, 10, 8))


def test_default_timestamp_is_used_when_omitted(workspace: Workspace) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    run_startup(workspace.config, workspace.state, workspace.artifacts, backend_factory=lambda c: display)
    assert workspace.load().revision == 1


def test_display_initialization_failure_preserves_state(workspace: Workspace) -> None:
    ordinary(workspace)

    def factory(configuration):
        raise DisplayBackendInitializationError("no display")

    with pytest.raises(ApplicationError, match="initialize"):
        run_startup(workspace.config, workspace.state, workspace.artifacts, now=at(10, 8), backend_factory=factory)
    state = workspace.load()
    assert state.revision == 1 and state.highest_reveal_stage == 0
    result, _ = workspace.run(at(10, 8))
    assert not result.selected_initial_quotation and workspace.load() == state


def test_display_update_failure_closes_backend_and_preserves_state(workspace: Workspace) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)
    with pytest.raises(ApplicationError, match="display update"):
        workspace.run(at(10, 19), display)
    assert display.closed == 1
    state = workspace.load()
    assert state.revision == 1 and state.highest_reveal_stage == 0
    result, _ = workspace.run(at(10, 19))
    assert result.presented_stage == 2 and workspace.load().revision == 1


def test_display_close_failure_is_reported_without_reselection(workspace: Workspace) -> None:
    ordinary(workspace)
    with pytest.raises(ApplicationError, match="cleanup"):
        workspace.run(at(10, 8), FakeDisplay(fail_close=True))
    assert workspace.load().revision == 1


def test_loaded_images_are_closed(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    closed: list[Image.Image] = []
    original = Image.Image.close

    def tracking_close(self):
        closed.append(self)
        return original(self)

    workspace.run(at(10, 8))
    monkeypatch.setattr(Image.Image, "close", tracking_close)
    display = FakeDisplay()
    workspace.run(at(10, 8), display)
    assert closed


def test_artifact_failure_preserves_selection(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.artifacts.parent.mkdir(exist_ok=True)
    workspace.artifacts.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(ApplicationError, match="artifact"):
        workspace.run(at(10, 8))
    assert workspace.load().revision == 1


def test_uncertain_commit_publication_is_resolved_by_reloading(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit

    def commit(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise StateCommitError("durability unconfirmed", published=True)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    result, _ = workspace.run(at(10, 8))
    assert result.state.revision == 1 and len(workspace.load().global_history) == 1


def test_unpublished_commit_failure_is_reported(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)

    def commit(self, *args, **kwargs):
        raise StateCommitError("disk full")

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    with pytest.raises(ApplicationError, match="disk full"):
        workspace.run(at(10, 8))
    assert workspace.load() is None


def test_uncertain_reveal_progress_publication_is_resolved_by_reloading(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    original = PersistentStateStore.advance_reveal_progress

    def advance(self, revision, stage):
        original(self, revision, stage)
        raise StateCommitError("durability unconfirmed", published=True)

    monkeypatch.setattr(PersistentStateStore, "advance_reveal_progress", advance)
    result, _ = workspace.run(at(10, 19))
    assert result.state.highest_reveal_stage == 2 and workspace.load().revision == 1


def test_failed_reveal_progress_update_is_reported(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))

    def advance(self, revision, stage):
        raise StateCommitError("disk full")

    monkeypatch.setattr(PersistentStateStore, "advance_reveal_progress", advance)
    display = FakeDisplay()
    with pytest.raises(ApplicationError, match="reveal progress"):
        workspace.run(at(10, 19), display)
    assert display.closed == 1 and workspace.load().highest_reveal_stage == 0


def test_keep_open_runs_before_backend_is_closed(workspace: Workspace) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    seen: list[tuple[str, int]] = []
    workspace.run(at(10, 8), display, keep_open=lambda backend: seen.append((backend, display.closed)))
    assert seen == [("waveshare-13in3-e", 0)] and display.closed == 1


def test_command_line_runs_startup(workspace: Workspace, monkeypatch, capsys) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    monkeypatch.setattr(application, "create_display_backend", lambda *args, **kwargs: display)
    arguments = [
        "--config",
        str(workspace.config),
        "--state",
        str(workspace.state),
        "--artifacts",
        str(workspace.artifacts),
    ]
    assert main(arguments) == 0
    assert "Selected selection 1" in capsys.readouterr().out
    assert main(arguments) == 0
    assert "Recovered selection 1" in capsys.readouterr().out
    assert workspace.load().revision == 1 and display.closed == 2


def test_command_line_reports_errors(workspace: Workspace, capsys) -> None:
    code = main(["--config", str(workspace.root / "nope.yaml"), "--state", "s.json", "--artifacts", "a"])
    assert code == 1
    assert "refrain:" in capsys.readouterr().err

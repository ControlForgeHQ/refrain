from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from random import Random
from threading import Event
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

import refrain.application as application
from refrain import (
    ApplicationError,
    DailyImagePreparationError,
    NoEligibleQuotationError,
    PersistentStateStore,
    StateCommitError,
    StateRecoveryError,
    run_application,
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
        "--once",
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


class RuntimeClock(Event):
    """Controlled clocks and interruptible waits; no real elapsed time."""

    def __init__(self, now: datetime, events=(), retries=()) -> None:
        super().__init__()
        self.now = now
        self.elapsed = 0.0
        self.events = iter(events)
        self.retries = iter(retries)
        self.deadlines: list[datetime] = []
        self.retry_delays: list[float] = []

    def move(self, now: datetime) -> None:
        difference = (now.astimezone(timezone.utc) - self.now.astimezone(timezone.utc)).total_seconds()
        self.elapsed += max(1.0, difference)
        self.now = now

    def scheduling_wait(self, deadline, shutdown, **kwargs):
        assert shutdown is self
        self.deadlines.append(deadline)
        event = next(self.events, None)
        if callable(event):
            event()
        elif event is None:
            self.set()
        else:
            self.move(event)
        return self.is_set()

    def wait(self, timeout=None):
        assert timeout is not None and 0 < timeout <= 300
        self.retry_delays.append(timeout)
        self.elapsed += timeout
        self.now += timedelta(seconds=timeout)
        callback = next(self.retries, None)
        if callback is not None:
            callback()
        else:
            self.set()
        return self.is_set()


def run_continuously(workspace, clock, monkeypatch, display=None, **kwargs):
    display = display or FakeDisplay()
    presentations = []
    initializations = []
    original = application.present_prepared_stage

    def present(backend, artifacts, stage):
        original(backend, artifacts, stage)
        presentations.append((artifacts.revision, stage))

    def initialize(configuration):
        initializations.append(configuration.display_backend)
        return display

    with monkeypatch.context() as patch:
        patch.setattr(application, "present_prepared_stage", present)
        run_application(
            workspace.config,
            workspace.state,
            workspace.artifacts,
            shutdown_event=clock,
            wall_clock=lambda: clock.now,
            monotonic_clock=lambda: clock.elapsed,
            scheduling_wait=clock.scheduling_wait,
            random_source=Random(1),
            backend_factory=kwargs.pop("backend_factory", initialize),
            **kwargs,
        )
    return presentations, initializations, display


def test_continuous_reveals_reuse_artifacts_and_one_backend(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = application.recover_prepared_daily_images
    recovered = []

    def recover(state, *args):
        recovered.append(state.revision)
        return original(state, *args)

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)

    def forbid_content_reload():
        monkeypatch.setattr(application, "load_content_library", lambda *args: pytest.fail("content reloaded"))
        clock.move(at(10, 12))

    clock = RuntimeClock(at(10, 7), [forbid_content_reload, at(10, 18), at(10, 19)])
    stages, initialized, display = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (1, 1), (1, 2)]
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1
    assert len(png_files(workspace.artifacts)) == 3
    assert recovered == [1]
    assert clock.deadlines[:2] == [at(10, 12), at(10, 18)]
    assert workspace.load().highest_reveal_stage == 2
    assert len(workspace.load().global_history) == 1


@pytest.mark.parametrize(
    ("extra", "events", "expected"),
    [
        ("", [at(10, 19)], [(1, 0), (1, 2)]),
        ('reveal:\n  source: "10:00"\n  attribution: "10:00"\n', [at(10, 10)], [(1, 0), (1, 1)]),
        ('reveal:\n  attribution: "09:00"\n', [at(10, 9), at(10, 12)], [(1, 0), (1, 1), (1, 2)]),
    ],
)
def test_continuous_missed_simultaneous_and_out_of_order_reveals(
    workspace, monkeypatch, extra, events, expected
) -> None:
    ordinary(workspace, extra=extra)
    stages, _, display = run_continuously(workspace, RuntimeClock(at(10, 7), events), monkeypatch)
    assert stages == expected and display.closed == 1
    assert workspace.load().highest_reveal_stage == expected[-1][1]


def test_continuous_daily_transitions_preserve_histories(workspace, monkeypatch) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n  - "Third."\n')
    clock = RuntimeClock(at(10, 7), [at(11, 6), at(11, 6), at(12, 6), at(13, 6)])
    stages, initialized, display = run_continuously(workspace, clock, monkeypatch)
    state = workspace.load()
    history = state.global_history
    assert stages == [(1, 0), (2, 0), (3, 0), (4, 0)]
    assert state.revision == len(history) == 4
    assert [record.display_date for record in history] == [date(2026, 3, day) for day in range(10, 14)]
    assert len({record.quotation_identity for record in history[:3]}) == 3
    assert state.repetition_history == {history[-1].quotation_identity}
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1
    assert len(png_files(workspace.artifacts)) == 1


def test_continuous_restart_is_conservative_and_reuses_committed_snapshot(workspace, monkeypatch) -> None:
    ordinary(workspace)
    run_continuously(workspace, RuntimeClock(at(10, 7)), monkeypatch)
    first = workspace.load()
    artifacts = {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)}
    for path in workspace.content.iterdir():
        path.unlink()
    monkeypatch.setattr(application, "load_content_library", lambda *args: pytest.fail("content reloaded"))
    stages, initialized, display = run_continuously(workspace, RuntimeClock(at(14, 19)), monkeypatch)
    state = workspace.load()
    assert stages == [(1, 2)]
    assert state.snapshot == first.snapshot and state.global_history == first.global_history
    assert state.repetition_history == first.repetition_history and state.highest_reveal_stage == 2
    assert {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)} == artifacts
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


def test_continuous_forward_jump_selects_only_current_date(workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 15\nquotations:\n  - "Special."\n')
    clock = RuntimeClock(at(10, 7), [at(15, 19)])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    state = workspace.load()
    assert stages == [(1, 0), (2, 0)]
    assert len(state.global_history) == 2 and state.snapshot.display_date == date(2026, 3, 15)
    assert state.snapshot.quotation_text == "Special."


def test_continuous_backward_jump_preserves_reveal_until_new_boundary(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(15, 19), [at(12, 4), at(12, 5), at(12, 6)])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 2), (2, 0)]
    state = workspace.load()
    assert [record.display_date for record in state.global_history] == [date(2026, 3, 15), date(2026, 3, 12)]


@pytest.mark.parametrize("published", [False, True])
def test_continuous_daily_commit_retry_and_uncertain_publication(workspace, monkeypatch, published) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit
    attempts = []

    def commit(self, proposal, snapshot):
        attempts.append(proposal.base_revision)
        if proposal.base_revision == 1 and attempts.count(1) == 1:
            if published:
                original(self, proposal, snapshot)
            raise StateCommitError("interrupted publication", published=published)
        return original(self, proposal, snapshot)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)]
    assert attempts == ([0, 1] if published else [0, 1, 1])
    assert len(workspace.load().global_history) == 2
    assert clock.retry_delays == ([] if published else [1])


def test_continuous_later_boundary_supersedes_failed_transition(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit
    attempted_dates = []

    def commit(self, proposal, snapshot):
        attempted_dates.append(snapshot.display_date)
        if snapshot.display_date == date(2026, 3, 11):
            raise StateCommitError("disk full")
        return original(self, proposal, snapshot)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: clock.move(at(14, 7))])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)]
    assert attempted_dates == [date(2026, 3, day) for day in (10, 11, 14)]
    assert [record.display_date.day for record in workspace.load().global_history] == [10, 14]


def test_continuous_preparation_failure_after_daily_commit_does_not_reselect(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = application.recover_prepared_daily_images
    attempts = []

    def recover(state, *args):
        attempts.append(state.revision)
        if state.revision == 2 and attempts.count(2) == 1:
            assert len(workspace.load().global_history) == 2
            raise DailyImagePreparationError("temporary preparation failure")
        return original(state, *args)

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: clock.move(at(11, 19))])
    stages, initialized, display = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 2)]
    assert attempts == [1, 2, 2]
    assert len(workspace.load().global_history) == 2
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_continuous_recovers_artifacts_damaged_between_reveals(workspace, monkeypatch, damage) -> None:
    ordinary(workspace)

    def damage_and_advance():
        for path in png_files(workspace.artifacts):
            if damage == "missing":
                path.unlink()
            else:
                path.write_bytes(b"damaged")
        clock.move(at(10, 12))

    clock = RuntimeClock(at(10, 7), [damage_and_advance], retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (1, 1)]
    assert clock.retry_delays == [1]
    assert workspace.load().revision == 1 and workspace.load().highest_reveal_stage == 1
    assert len(png_files(workspace.artifacts)) >= 3


def test_continuous_display_retry_without_event_or_reselection(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)
    clock = RuntimeClock(at(10, 7), retries=[lambda: setattr(display, "fail_update", False)])
    stages, initialized, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 0)] and clock.retry_delays == [1]
    assert workspace.load().revision == len(workspace.load().global_history) == 1
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


def test_continuous_failed_display_skips_to_newer_desired_selection(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)

    def recover_display():
        display.fail_update = False
        clock.move(at(14, 19))

    clock = RuntimeClock(at(10, 7), retries=[recover_display])
    stages, initialized, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(2, 2)]
    assert len(workspace.load().global_history) == 2
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


def test_continuous_reveal_persistence_retry_never_hides_successful_presentation(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.advance_reveal_progress
    attempts = []

    def advance(self, revision, stage):
        attempts.append(stage)
        if len(attempts) == 1:
            raise StateCommitError("disk full")
        return original(self, revision, stage)

    monkeypatch.setattr(PersistentStateStore, "advance_reveal_progress", advance)
    clock = RuntimeClock(at(10, 19), retries=[lambda: clock.move(at(10, 7))])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 2)] and attempts == [2, 2]
    assert workspace.load().highest_reveal_stage == 2


def test_continuous_initialization_retry(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    attempts = []

    def factory(configuration):
        attempts.append(configuration.display_backend)
        if len(attempts) == 1:
            raise DisplayBackendInitializationError("temporarily unavailable")
        return display

    clock = RuntimeClock(at(10, 7), retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch, backend_factory=factory)
    assert stages == [(1, 0)] and len(attempts) == 2 and display.closed == 1
    assert workspace.load().revision == 1


def test_continuous_shutdown_during_recovery_bounds_retries_and_logs(workspace, monkeypatch, caplog) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)
    clock = RuntimeClock(at(10, 7), retries=[lambda: None] * 8)
    with caplog.at_level(logging.WARNING):
        stages, _, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [] and display.closed == 1
    assert clock.retry_delays == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert caplog.text.count("Application operation failed") == 1
    assert workspace.load().revision == 1 and png_files(workspace.artifacts)


def test_continuous_content_failure_preserves_previous_state_for_retry(workspace, monkeypatch) -> None:
    ordinary(workspace)
    path = workspace.content / "ordinary.yaml"
    original = path.read_text(encoding="utf-8")
    previous = []

    def remove_content():
        previous.append(workspace.load())
        path.unlink()
        clock.move(at(11, 6))

    def restore_content():
        assert workspace.load() == previous[0]
        path.write_text(original, encoding="utf-8")

    clock = RuntimeClock(at(10, 7), [remove_content], retries=[restore_content])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)] and clock.retry_delays == [1]
    assert len(workspace.load().global_history) == 2


@pytest.mark.parametrize("failure", ["configuration", "state"])
def test_continuous_unrecoverable_errors_terminate_without_retry(workspace, monkeypatch, failure) -> None:
    ordinary(workspace)
    if failure == "configuration":
        workspace.config.write_text("invalid: true", encoding="utf-8")
    else:
        workspace.state.parent.mkdir()
        workspace.state.write_text("corrupt", encoding="utf-8")
    clock = RuntimeClock(at(10, 7))
    with pytest.raises(ApplicationError, match="configuration|persistent state"):
        run_continuously(workspace, clock, monkeypatch)
    assert clock.retry_delays == [] and clock.deadlines == []


def test_continuous_uncertain_publication_with_temporary_reload_failure(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original_commit = PersistentStateStore.commit
    original_load = PersistentStateStore.load
    unreadable = False

    def commit(self, *args):
        nonlocal unreadable
        original_commit(self, *args)
        unreadable = True
        raise StateCommitError("durability unconfirmed", published=True)

    def load(self):
        if unreadable:
            raise StateRecoveryError("temporary read failure") from OSError("temporarily unavailable")
        return original_load(self)

    def recover_storage():
        nonlocal unreadable
        unreadable = False

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    monkeypatch.setattr(PersistentStateStore, "load", load)
    clock = RuntimeClock(at(10, 7), retries=[recover_storage])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0)] and clock.retry_delays == [1]
    assert len(workspace.load().global_history) == 1


def test_continuous_real_scheduling_wait_is_interrupted_by_shutdown(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 7))
    clock.scheduling_wait = application.wait_for_scheduling_event
    _, _, display = run_continuously(workspace, clock, monkeypatch)
    assert clock.is_set() and display.closed == 1
    assert clock.retry_delays == [300]


def test_continuous_shutdown_during_update_persists_successful_reveal(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 19))
    display = FakeDisplay()
    original = display.update

    def update(image):
        original(image)
        clock.set()

    display.update = update
    stages, _, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 2)] and display.closed == 1
    assert workspace.load().highest_reveal_stage == 2


def test_continuous_slow_preparation_rechecks_latest_stage_before_presenting(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 7))
    original = application.recover_prepared_daily_images

    def recover(*args):
        images = original(*args)
        clock.move(at(10, 19))
        return images

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 2)] and workspace.load().highest_reveal_stage == 2


def test_continuous_daily_display_failure_retains_commit_and_prepared_images(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    prepared = []
    original = application.recover_prepared_daily_images

    def recover(state, *args):
        prepared.append(state.revision)
        return original(state, *args)

    def fail_daily_update():
        display.fail_update = True
        clock.move(at(11, 6))

    def restore_display():
        state = workspace.load()
        assert state.revision == len(state.global_history) == 2
        assert len(png_files(workspace.artifacts)) == 3
        display.fail_update = False

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
    clock = RuntimeClock(at(10, 7), [fail_daily_update], retries=[restore_display])
    stages, initialized, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 0), (2, 0)] and prepared == [1, 2]
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1
    assert len(workspace.load().global_history) == 2


def test_command_line_defaults_to_continuous_and_restores_signal_handlers(workspace, monkeypatch) -> None:
    import signal

    import refrain.__main__ as command_line

    calls = []
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def run(config, state, artifacts, *, shutdown_event):
        calls.append((config, state, artifacts))
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert shutdown_event.is_set()

    monkeypatch.setattr(command_line, "run_application", run)
    assert (
        main(
            [
                "--config",
                str(workspace.config),
                "--state",
                str(workspace.state),
                "--artifacts",
                str(workspace.artifacts),
            ]
        )
        == 0
    )
    assert calls == [(str(workspace.config), str(workspace.state), str(workspace.artifacts))]
    assert {sig: signal.getsignal(sig) for sig in handlers} == handlers

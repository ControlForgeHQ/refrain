from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

import pytest

from refrain import (
    ApplicationConfiguration,
    DailySnapshot,
    DisplayDayBoundary,
    DisplayDayBoundaryObserver,
    PersistentState,
    PresentationRegion,
    ResolvedFont,
    RevealSchedule,
    SchedulingAction,
    SchedulingContext,
    StateCommitError,
    evaluate_scheduling,
    next_scheduling_deadline,
    normalize_quotation,
    wait_for_scheduling_event,
)


def make_configuration(
    *, timezone_name: str = "America/New_York", day_start: str = "06:00"
) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        file=Path("/config.yaml"),
        display_backend="window",
        timezone=ZoneInfo(timezone_name),
        day_start=time.fromisoformat(day_start),
        content_directory=Path("/content"),
        reveal=RevealSchedule(time.fromisoformat(day_start), time(12), time(18)),
        presentation_region=PresentationRegion(0, 0, 1, 1),
        fonts={},
        default_fonts=(),
        min_font_size=12,
        max_font_size=32,
    )


def make_state(
    *,
    display_date: date = date(2026, 10, 26),
    day_start: str = "06:00",
    reveal_schedule: dict[str, str] | None = None,
    highest_reveal_stage: int = 0,
    timezone_name: str = "America/New_York",
) -> PersistentState:
    text = "A committed quotation."
    snapshot = DailySnapshot(
        quotation_text=text,
        quotation_identity=normalize_quotation(text),
        font=ResolvedFont(identifier="test-font", data=b"font bytes"),
        presentation_metadata={"presentation_style": "centered", "source": "Source", "attribution": "Author"},
        reveal_schedule=reveal_schedule or {"quotation": day_start, "source": "12:00", "attribution": "18:00"},
        layout={},
        scheduling=SchedulingContext(display_date, timezone_name, day_start),
    )
    return PersistentState(
        revision=4,
        snapshot=snapshot,
        global_history=(),
        repetition_history=frozenset(),
        highest_reveal_stage=highest_reveal_stage,
    )


def test_observer_recognizes_one_ordinary_day_start_boundary() -> None:
    observer = DisplayDayBoundaryObserver(make_configuration())
    zone = ZoneInfo("America/New_York")

    assert observer.observe(datetime(2026, 10, 26, 5, 59, tzinfo=zone), 100.0, 4) is None
    boundary = observer.observe(datetime(2026, 10, 26, 6, 0, tzinfo=zone), 160.0, 4)

    assert boundary == DisplayDayBoundary(date(2026, 10, 26), 4)
    assert observer.observe(datetime(2026, 10, 26, 6, 1, tzinfo=zone), 220.0, 4) == boundary
    assert observer.observe(datetime(2026, 10, 26, 6, 2, tzinfo=zone), 280.0, 5) is None


def test_uncommitted_boundary_is_reused_until_selection_revision_advances() -> None:
    observer = DisplayDayBoundaryObserver(make_configuration())
    zone = ZoneInfo("America/New_York")
    state = make_state(display_date=date(2026, 10, 25))
    observer.observe(datetime(2026, 10, 26, 5, 59, tzinfo=zone), 100.0, state.revision)
    boundary = observer.observe(datetime(2026, 10, 26, 6, 0, tzinfo=zone), 160.0, state.revision)
    assert boundary == DisplayDayBoundary(date(2026, 10, 26), state.revision)

    with pytest.raises(StateCommitError, match="simulated selection failure"):
        raise StateCommitError("simulated selection failure")
    failed_commit_state = state
    assert failed_commit_state.revision == state.revision
    first_decision = evaluate_scheduling(
        datetime(2026, 10, 26, 6, 1, tzinfo=zone), make_configuration(), state, boundary
    )
    repeated_boundary = observer.observe(datetime(2026, 10, 26, 6, 1, tzinfo=zone), 220.0, failed_commit_state.revision)
    retry_decision = evaluate_scheduling(
        datetime(2026, 10, 26, 6, 1, tzinfo=zone), make_configuration(), failed_commit_state, repeated_boundary
    )

    assert first_decision == retry_decision
    assert retry_decision.action is SchedulingAction.NEW_SELECTION
    assert retry_decision.display_date == date(2026, 10, 26)
    assert repeated_boundary == boundary

    committed_state = replace(state, revision=state.revision + 1)
    assert observer.observe(datetime(2026, 10, 26, 6, 2, tzinfo=zone), 280.0, committed_state.revision) is None
    stale_decision = evaluate_scheduling(
        datetime(2026, 10, 26, 6, 2, tzinfo=zone), make_configuration(), committed_state, boundary
    )
    assert stale_decision.action is not SchedulingAction.NEW_SELECTION


def test_observer_forward_jump_selects_current_date_without_replaying_skipped_days() -> None:
    observer = DisplayDayBoundaryObserver(make_configuration())
    zone = ZoneInfo("America/New_York")
    observer.observe(datetime(2026, 10, 26, 5, 55, tzinfo=zone), 100.0, 4)

    boundary = observer.observe(datetime(2026, 10, 29, 7, 0, tzinfo=zone), 160.0, 4)

    assert boundary == DisplayDayBoundary(date(2026, 10, 29), 4)
    assert observer.observe(datetime(2026, 10, 29, 7, 1, tzinfo=zone), 220.0, 4) == boundary


def test_observer_backward_adjustment_waits_for_a_later_observed_boundary() -> None:
    observer = DisplayDayBoundaryObserver(make_configuration())
    zone = ZoneInfo("America/New_York")
    observer.observe(datetime(2026, 10, 26, 6, 1, tzinfo=zone), 100.0, 4)

    assert observer.observe(datetime(2026, 10, 12, 4, 0, tzinfo=zone), 101.0, 4) is None
    boundary = observer.observe(datetime(2026, 10, 12, 6, 0, tzinfo=zone), 7301.0, 4)

    assert boundary == DisplayDayBoundary(date(2026, 10, 12), 4)


def test_first_observation_after_startup_does_not_infer_a_historical_boundary() -> None:
    observer = DisplayDayBoundaryObserver(make_configuration())

    assert observer.observe(datetime(2026, 10, 27, 8, 0, tzinfo=ZoneInfo("America/New_York")), 100.0, 4) is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (
            datetime(2026, 3, 8, 5, 59, tzinfo=ZoneInfo("America/New_York")),
            datetime(2026, 3, 8, 6, 0, tzinfo=ZoneInfo("America/New_York")),
            date(2026, 3, 8),
        ),
        (
            datetime(2026, 11, 1, 5, 59, tzinfo=ZoneInfo("America/New_York")),
            datetime(2026, 11, 1, 6, 0, tzinfo=ZoneInfo("America/New_York")),
            date(2026, 11, 1),
        ),
        (
            datetime(2026, 12, 31, 5, 59, tzinfo=ZoneInfo("America/New_York")),
            datetime(2026, 12, 31, 6, 0, tzinfo=ZoneInfo("America/New_York")),
            date(2026, 12, 31),
        ),
        (
            datetime(2026, 12, 31, 23, 59, tzinfo=ZoneInfo("America/New_York")),
            datetime(2027, 1, 1, 6, 0, tzinfo=ZoneInfo("America/New_York")),
            date(2027, 1, 1),
        ),
    ],
)
def test_observer_recognizes_dst_and_calendar_boundaries(before: datetime, after: datetime, expected: date) -> None:
    observer = DisplayDayBoundaryObserver(make_configuration())
    observer.observe(before, 100.0, 4)

    assert observer.observe(after, 160.0, 4) == DisplayDayBoundary(expected, 4)


def test_observer_does_not_duplicate_a_fall_back_ambiguous_day_start() -> None:
    observer = DisplayDayBoundaryObserver(make_configuration(day_start="01:30"))
    zone = ZoneInfo("America/New_York")
    observer.observe(datetime(2026, 11, 1, 1, 29, fold=0, tzinfo=zone), 100.0, 4)

    first_occurrence = observer.observe(datetime(2026, 11, 1, 1, 31, fold=0, tzinfo=zone), 220.0, 4)
    assert observer.observe(datetime(2026, 11, 1, 1, 0, fold=1, tzinfo=zone), 1960.0, 4) == first_occurrence
    assert observer.observe(datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=zone), 3760.0, 5) is None
    second_occurrence = observer.observe(datetime(2026, 11, 1, 1, 31, fold=1, tzinfo=zone), 3820.0, 5)

    assert first_occurrence == DisplayDayBoundary(date(2026, 11, 1), 4)
    assert second_occurrence is None


def test_next_deadline_uses_committed_reveal_schedule_before_day_boundary() -> None:
    zone = ZoneInfo("America/New_York")
    state = make_state()

    deadline = next_scheduling_deadline(datetime(2026, 10, 26, 10, 0, tzinfo=zone), make_configuration(), state)

    assert deadline == datetime(2026, 10, 26, 12, 0, tzinfo=zone)


def test_missing_state_requests_immediate_initial_scheduling() -> None:
    current_time = datetime(2026, 10, 26, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert next_scheduling_deadline(current_time, make_configuration(), None) == current_time


def test_missed_reveal_time_is_due_immediately_and_simultaneous_events_share_deadline() -> None:
    zone = ZoneInfo("America/New_York")
    state = make_state(reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "12:00"})

    immediate = next_scheduling_deadline(datetime(2026, 10, 26, 13, 0, tzinfo=zone), make_configuration(), state)
    simultaneous = next_scheduling_deadline(datetime(2026, 10, 26, 10, 0, tzinfo=zone), make_configuration(), state)

    assert immediate == datetime(2026, 10, 26, 13, 0, tzinfo=zone)
    assert simultaneous == datetime(2026, 10, 26, 12, 0, tzinfo=zone)


def test_reveal_deadline_uses_snapshot_timezone_and_returns_configured_timezone() -> None:
    zone = ZoneInfo("America/New_York")
    state = make_state(
        timezone_name="UTC",
        highest_reveal_stage=1,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
    )

    deadline = next_scheduling_deadline(datetime(2026, 10, 26, 10, 0, tzinfo=zone), make_configuration(), state)

    assert deadline == datetime(2026, 10, 26, 14, 0, tzinfo=zone)


def test_next_deadline_resolves_day_start_across_dst_gap_and_fold() -> None:
    spring_config = make_configuration(day_start="02:30")
    spring_deadline = next_scheduling_deadline(
        datetime(2026, 3, 8, 1, 45, tzinfo=ZoneInfo("America/New_York")),
        spring_config,
        make_state(highest_reveal_stage=2),
    )
    fall_config = make_configuration(day_start="01:30")
    fall_state = make_state(
        display_date=date(2026, 11, 1),
        day_start="01:30",
        reveal_schedule={"quotation": "01:30", "source": "12:00", "attribution": "18:00"},
        highest_reveal_stage=2,
    )
    fall_deadline = next_scheduling_deadline(
        datetime(2026, 11, 1, 1, 0, fold=0, tzinfo=ZoneInfo("America/New_York")), fall_config, fall_state
    )
    second_fold_deadline = next_scheduling_deadline(
        datetime(2026, 11, 1, 1, 15, fold=1, tzinfo=ZoneInfo("America/New_York")), fall_config, fall_state
    )

    assert spring_deadline == datetime(2026, 3, 8, 3, 0, tzinfo=ZoneInfo("America/New_York"))
    assert fall_deadline == datetime(2026, 11, 1, 1, 30, fold=0, tzinfo=ZoneInfo("America/New_York"))
    assert second_fold_deadline == datetime(2026, 11, 2, 1, 30, tzinfo=ZoneInfo("America/New_York"))


class FakeWaitEvent:
    def __init__(
        self,
        wall: list[float],
        monotonic: list[float],
        *,
        interrupt: bool = False,
        clock_change: float = 0,
    ) -> None:
        self.wall = wall
        self.monotonic = monotonic
        self.interrupt = interrupt
        self.clock_change = clock_change
        self.waited: list[float] = []
        self.set = False

    def is_set(self) -> bool:
        return self.set

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.waited.append(timeout)
        self.wall[0] += timeout + self.clock_change
        self.monotonic[0] += timeout
        if self.interrupt:
            self.set = True
        return self.set


@pytest.fixture
def fake_clocks() -> tuple[list[float], list[float]]:
    return [0.0], [0.0]


def test_wait_is_interrupted_by_external_wake_event(fake_clocks: tuple[list[float], list[float]]) -> None:
    wall, monotonic = fake_clocks
    event = FakeWaitEvent(wall, monotonic, interrupt=True)

    def wall_clock() -> datetime:
        return datetime.fromtimestamp(wall[0], tz=timezone.utc)

    interrupted = wait_for_scheduling_event(
        datetime.fromtimestamp(3600, tz=timezone.utc),
        event,  # type: ignore[arg-type]
        wall_clock=wall_clock,
        monotonic_clock=lambda: monotonic[0],
        max_clock_check_interval=300,
    )

    assert interrupted is True
    assert event.waited == [300]


def test_wait_returns_for_deadline_or_clock_correction(
    fake_clocks: tuple[list[float], list[float]],
) -> None:
    wall, monotonic = fake_clocks
    event = FakeWaitEvent(wall, monotonic)

    def wall_clock() -> datetime:
        return datetime.fromtimestamp(wall[0], tz=timezone.utc)

    due = wait_for_scheduling_event(
        datetime.fromtimestamp(120, tz=timezone.utc),
        event,  # type: ignore[arg-type]
        wall_clock=wall_clock,
        monotonic_clock=lambda: monotonic[0],
        max_clock_check_interval=300,
    )
    assert due is False
    assert event.waited == [120]

    wall[0] = 0
    monotonic[0] = 0
    adjusted_event = FakeWaitEvent(wall, monotonic, clock_change=3600)
    adjusted = wait_for_scheduling_event(
        datetime.fromtimestamp(7200, tz=timezone.utc),
        adjusted_event,  # type: ignore[arg-type]
        wall_clock=wall_clock,
        monotonic_clock=lambda: monotonic[0],
        max_clock_check_interval=300,
    )

    assert adjusted is False
    assert adjusted_event.waited == [300]


def test_wait_can_be_interrupted_by_a_pre_set_shutdown_event() -> None:
    event = Event()
    event.set()

    assert wait_for_scheduling_event(datetime(2027, 1, 1, tzinfo=timezone.utc), event) is True

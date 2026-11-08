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
    DisplayBackendConfiguration,
    PersistentState,
    PresentationRegion,
    RevealSchedule,
    SchedulingAction,
    SchedulingContext,
    evaluate_scheduling,
    next_scheduling_deadline,
    normalize_quotation,
    wait_for_scheduling_event,
)
def make_configuration(*, day_start: str = "06:00") -> ApplicationConfiguration:
    return ApplicationConfiguration(
        file=Path("/config.yaml"),
        display_backends=(DisplayBackendConfiguration("window"),),
        day_start=time.fromisoformat(day_start),
        content_directory=Path("/content"),
        reveal=RevealSchedule(time(12), time(18)),
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
) -> PersistentState:
    text = "A committed quotation."
    snapshot = DailySnapshot(
        entry_id="entry",
        quotation_text=text,
        quotation_identity=normalize_quotation(text),
        source="Source",
        attribution="Author",
        presentation_style="centered",
        font=None,
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule=reveal_schedule or {"quotation": day_start, "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(display_date, day_start),
    )
    return PersistentState(
        revision=4,
        snapshot=snapshot,
        repetition_history=frozenset(),
        highest_reveal_stage=highest_reveal_stage,
    )


def test_next_deadline_uses_committed_reveal_schedule_before_day_boundary() -> None:
    zone = ZoneInfo("America/New_York")
    state = make_state()

    deadline = next_scheduling_deadline(datetime(2026, 10, 26, 10, 0, tzinfo=zone), make_configuration(), state)

    assert deadline == datetime(2026, 10, 26, 12, 0, tzinfo=zone)


def test_missing_state_requests_immediate_initial_scheduling() -> None:
    current_time = datetime(2026, 10, 26, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert next_scheduling_deadline(current_time, make_configuration(), None) == current_time


def test_logical_date_mismatch_requests_immediate_scheduling() -> None:
    current_time = datetime(2026, 10, 27, 7, 0, tzinfo=ZoneInfo("America/New_York"))

    assert next_scheduling_deadline(current_time, make_configuration(), make_state()) == current_time


def test_missed_reveal_time_is_due_immediately_and_simultaneous_events_share_deadline() -> None:
    zone = ZoneInfo("America/New_York")
    state = make_state(reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "12:00"})

    immediate = next_scheduling_deadline(datetime(2026, 10, 26, 13, 0, tzinfo=zone), make_configuration(), state)
    simultaneous = next_scheduling_deadline(datetime(2026, 10, 26, 10, 0, tzinfo=zone), make_configuration(), state)

    assert immediate == datetime(2026, 10, 26, 13, 0, tzinfo=zone)
    assert simultaneous == datetime(2026, 10, 26, 12, 0, tzinfo=zone)


def test_reveal_deadline_uses_operating_system_local_timezone_and_returns_utc() -> None:
    zone = ZoneInfo("America/New_York")
    state = make_state(
        highest_reveal_stage=1,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
    )

    deadline = next_scheduling_deadline(datetime(2026, 10, 26, 10, 0, tzinfo=zone), make_configuration(), state)

    assert deadline == datetime(2026, 10, 26, 22, 0, tzinfo=timezone.utc)


def test_next_deadline_resolves_day_start_across_dst_gap_and_fold() -> None:
    spring_config = make_configuration(day_start="02:30")
    spring_deadline = next_scheduling_deadline(
        datetime(2026, 3, 8, 1, 45, tzinfo=ZoneInfo("America/New_York")),
        spring_config,
        make_state(display_date=date(2026, 3, 7), day_start="02:30", highest_reveal_stage=2),
    )
    fall_config = make_configuration(day_start="01:30")
    fall_state = make_state(
        display_date=date(2026, 10, 31),
        day_start="01:30",
        reveal_schedule={"quotation": "01:30", "source": "12:00", "attribution": "18:00"},
        highest_reveal_stage=2,
    )
    second_fold_state = make_state(
        display_date=date(2026, 11, 1),
        day_start="01:30",
        reveal_schedule={"quotation": "01:30", "source": "12:00", "attribution": "18:00"},
        highest_reveal_stage=2,
    )
    fall_deadline = next_scheduling_deadline(
        datetime(2026, 11, 1, 1, 0, fold=0, tzinfo=ZoneInfo("America/New_York")), fall_config, fall_state
    )
    second_fold_deadline = next_scheduling_deadline(
        datetime(2026, 11, 1, 1, 15, fold=1, tzinfo=ZoneInfo("America/New_York")),
        fall_config,
        second_fold_state,
    )

    assert spring_deadline == datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
    assert fall_deadline == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    assert second_fold_deadline == datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)


def test_nonexistent_reveal_time_becomes_due_at_first_valid_local_instant() -> None:
    state = make_state(
        display_date=date(2026, 3, 8),
        day_start="01:00",
        reveal_schedule={"quotation": "01:00", "source": "02:30", "attribution": "18:00"},
    )
    before_gap = datetime(2026, 3, 8, 1, 45, tzinfo=ZoneInfo("America/New_York"))

    deadline = next_scheduling_deadline(before_gap, make_configuration(day_start="01:00"), state)
    due = evaluate_scheduling(
        datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc),
        make_configuration(day_start="01:00"),
        state,
    )

    assert deadline == datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)
    assert due.action is SchedulingAction.ADVANCE_REVEAL
    assert due.required_reveal_stage == 1


def test_ambiguous_reveal_time_uses_first_occurrence_and_never_regresses() -> None:
    state = make_state(
        display_date=date(2026, 11, 1),
        day_start="00:30",
        reveal_schedule={"quotation": "00:30", "source": "01:30", "attribution": "02:00"},
    )
    before_first_occurrence = datetime(2026, 11, 1, 1, 25, fold=0, tzinfo=ZoneInfo("America/New_York"))

    deadline = next_scheduling_deadline(before_first_occurrence, make_configuration(day_start="00:30"), state)
    first_occurrence = evaluate_scheduling(
        datetime(2026, 11, 1, 5, 35, tzinfo=timezone.utc), make_configuration(day_start="00:30"), state
    )
    after_fallback = evaluate_scheduling(
        datetime(2026, 11, 1, 6, 10, tzinfo=timezone.utc),
        make_configuration(day_start="00:30"),
        replace(state, highest_reveal_stage=1),
    )

    assert deadline == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    assert first_occurrence.required_reveal_stage == 1
    assert after_fallback.required_reveal_stage == 1
    assert after_fallback.action is SchedulingAction.NO_ACTION


def test_half_hour_dst_gap_resolves_without_assuming_hour_transitions(set_local_timezone) -> None:
    zone = ZoneInfo("Australia/Lord_Howe")
    set_local_timezone(zone)
    state = make_state(
        display_date=date(2026, 10, 4),
        day_start="01:00",
        reveal_schedule={"quotation": "01:00", "source": "02:15", "attribution": "18:00"},
    )

    deadline = next_scheduling_deadline(
        datetime(2026, 10, 4, 1, 45, tzinfo=zone),
        make_configuration(day_start="01:00"),
        state,
    )

    assert deadline == datetime(2026, 10, 3, 15, 30, tzinfo=timezone.utc)


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

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from refrain import (
    ApplicationConfiguration,
    DailySnapshot,
    DisplayDayBoundary,
    PersistentState,
    PresentationRegion,
    ResolvedFont,
    RevealSchedule,
    SchedulingAction,
    SchedulingContext,
    SchedulingEvaluationError,
    evaluate_scheduling,
    normalize_quotation,
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
    timezone_name: str = "America/New_York",
    day_start: str = "06:00",
    reveal_schedule: dict[str, str] | None = None,
    metadata: dict[str, str | None] | None = None,
    highest_reveal_stage: int = 0,
    revision: int = 1,
) -> PersistentState:
    text = "A committed quotation."
    snapshot = DailySnapshot(
        quotation_text=text,
        quotation_identity=normalize_quotation(text),
        font=ResolvedFont(identifier="test-font", data=b"font bytes"),
        presentation_metadata=metadata
        or {"presentation_style": "centered", "source": "Source", "attribution": "Author"},
        reveal_schedule=reveal_schedule or {"quotation": day_start, "source": "12:00", "attribution": "18:00"},
        layout={},
        scheduling=SchedulingContext(display_date, timezone_name, day_start),
    )
    return PersistentState(
        revision=revision,
        snapshot=snapshot,
        global_history=(),
        repetition_history=frozenset(),
        highest_reveal_stage=highest_reveal_stage,
    )


@pytest.mark.parametrize(
    ("current_time", "expected_date"),
    [
        (datetime(2026, 10, 26, 9, 59, tzinfo=timezone.utc), date(2026, 10, 25)),
        (datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc), date(2026, 10, 26)),
        (datetime(2026, 10, 26, 10, 1, tzinfo=timezone.utc), date(2026, 10, 26)),
        (datetime(2027, 4, 1, 9, 59, tzinfo=timezone.utc), date(2027, 3, 31)),
        (datetime(2027, 1, 1, 11, 0, tzinfo=timezone.utc), date(2027, 1, 1)),
        (datetime(2027, 1, 1, 10, 59, tzinfo=timezone.utc), date(2026, 12, 31)),
    ],
)
def test_initial_display_date_uses_local_day_start_and_calendar_dates(
    current_time: datetime, expected_date: date
) -> None:
    decision = evaluate_scheduling(current_time, make_configuration(), None)

    assert decision.action is SchedulingAction.INITIAL_SELECTION
    assert decision.display_date == expected_date
    assert decision.required_reveal_stage is None


@pytest.mark.parametrize(
    ("current_time", "expected_date"),
    [
        (datetime(2026, 3, 9, 9, 30, tzinfo=timezone.utc), date(2026, 3, 8)),
        (datetime(2026, 11, 2, 10, 30, tzinfo=timezone.utc), date(2026, 11, 1)),
    ],
)
def test_initial_date_uses_calendar_arithmetic_across_dst(current_time: datetime, expected_date: date) -> None:
    decision = evaluate_scheduling(current_time, make_configuration(), None)

    assert decision.display_date == expected_date


def test_initial_date_uses_configured_timezone_not_timestamp_timezone() -> None:
    current_time = datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc)

    decision = evaluate_scheduling(current_time, make_configuration(), None)

    assert decision.display_date == date(2026, 10, 25)


@pytest.mark.parametrize(
    ("current_time", "stage"),
    [
        (datetime(2026, 10, 26, 6, 0, tzinfo=ZoneInfo("America/New_York")), 0),
        (datetime(2026, 10, 26, 12, 0, tzinfo=ZoneInfo("America/New_York")), 1),
        (datetime(2026, 10, 26, 19, 0, tzinfo=ZoneInfo("America/New_York")), 2),
    ],
)
def test_reveal_stage_follows_snapshot_schedule(current_time: datetime, stage: int) -> None:
    decision = evaluate_scheduling(current_time, make_configuration(), make_state())

    assert decision.action is (SchedulingAction.ADVANCE_REVEAL if stage else SchedulingAction.NO_ACTION)
    assert decision.required_reveal_stage == stage


def test_missed_reveal_times_advance_directly_to_latest_stage() -> None:
    decision = evaluate_scheduling(
        datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc),
        make_configuration(),
        make_state(),
    )

    assert decision.action is SchedulingAction.ADVANCE_REVEAL
    assert decision.required_reveal_stage == 2


def test_simultaneous_reveals_share_a_stage() -> None:
    state = make_state(reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "12:00"})

    decision = evaluate_scheduling(
        datetime(2026, 10, 26, 12, 0, tzinfo=ZoneInfo("America/New_York")), make_configuration(), state
    )

    assert decision.required_reveal_stage == 1


def test_nonexistent_dst_reveal_time_becomes_due_after_the_clock_skips_it() -> None:
    state = make_state(
        display_date=date(2026, 3, 8),
        day_start="01:00",
        reveal_schedule={"quotation": "01:00", "source": "02:30", "attribution": "18:00"},
    )
    configuration = make_configuration(day_start="01:00")

    decision = evaluate_scheduling(
        datetime(2026, 3, 8, 3, 0, tzinfo=ZoneInfo("America/New_York")),
        configuration,
        state,
    )

    assert decision.required_reveal_stage == 1


@pytest.mark.parametrize(
    ("metadata", "schedule", "expected_stage"),
    [
        ({"presentation_style": "centered"}, {"quotation": "06:00"}, 0),
        (
            {"presentation_style": "centered", "attribution": "Author"},
            {"quotation": "06:00", "attribution": "18:00"},
            1,
        ),
    ],
)
def test_absent_optional_fields_do_not_add_reveal_stages(
    metadata: dict[str, str | None], schedule: dict[str, str], expected_stage: int
) -> None:
    state = make_state(metadata=metadata, reveal_schedule=schedule)

    decision = evaluate_scheduling(
        datetime(2026, 10, 26, 19, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        state,
    )

    assert decision.required_reveal_stage == expected_stage


def test_committed_reveal_progress_never_regresses_after_backward_clock_change() -> None:
    state = make_state(highest_reveal_stage=2)

    decision = evaluate_scheduling(
        datetime(2026, 10, 25, 4, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        state,
    )

    assert decision.action is SchedulingAction.NO_ACTION
    assert decision.required_reveal_stage == 2
    assert decision.display_date is None


def test_forward_date_mismatch_does_not_reselect_without_boundary_observation() -> None:
    decision = evaluate_scheduling(
        datetime(2026, 10, 27, 7, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        make_state(),
    )

    assert decision.action is SchedulingAction.ADVANCE_REVEAL
    assert decision.required_reveal_stage == 2
    assert decision.display_date is None


def test_observed_boundary_can_select_an_earlier_display_date() -> None:
    state = make_state()
    boundary = DisplayDayBoundary(date(2026, 10, 12), state.revision)

    decision = evaluate_scheduling(
        datetime(2026, 10, 12, 6, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        state,
        boundary,
    )

    assert decision == evaluate_scheduling(
        datetime(2026, 10, 12, 6, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        state,
        boundary,
    )
    assert decision.action is SchedulingAction.NEW_SELECTION
    assert decision.display_date == date(2026, 10, 12)


def test_later_boundary_is_recognized_after_backward_clock_adjustment() -> None:
    state = make_state()
    current_time = datetime(2026, 10, 12, 4, 0, tzinfo=ZoneInfo("America/New_York"))

    before_boundary = evaluate_scheduling(current_time, make_configuration(), state)
    at_boundary = evaluate_scheduling(
        datetime(2026, 10, 12, 6, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        state,
        DisplayDayBoundary(date(2026, 10, 12), state.revision),
    )

    assert before_boundary.action is SchedulingAction.NO_ACTION
    assert before_boundary.display_date is None
    assert at_boundary.action is SchedulingAction.NEW_SELECTION
    assert at_boundary.display_date == date(2026, 10, 12)


def test_repeated_boundary_observation_is_stale_after_selection_revision_changes() -> None:
    boundary = DisplayDayBoundary(date(2026, 10, 12), state_revision=1)
    state_after_selection = make_state(display_date=date(2026, 10, 12), revision=2)

    decision = evaluate_scheduling(
        datetime(2026, 10, 12, 6, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        state_after_selection,
        boundary,
    )

    assert decision.action is SchedulingAction.NO_ACTION
    assert decision.display_date is None


def test_boundary_observation_with_different_revision_is_not_recognized() -> None:
    decision = evaluate_scheduling(
        datetime(2026, 10, 26, 7, 0, tzinfo=ZoneInfo("America/New_York")),
        make_configuration(),
        make_state(),
        DisplayDayBoundary(date(2026, 10, 27), state_revision=0),
    )

    assert decision.action is SchedulingAction.NO_ACTION


def test_initial_selection_uses_current_calendar_date_not_unmatched_boundary() -> None:
    decision = evaluate_scheduling(
        datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc),
        make_configuration(),
        None,
        DisplayDayBoundary(date(2026, 10, 20), state_revision=0),
    )

    assert decision.action is SchedulingAction.INITIAL_SELECTION
    assert decision.display_date == date(2026, 10, 26)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(SchedulingEvaluationError, match="timezone-aware"):
        evaluate_scheduling(datetime(2026, 10, 26, 10, 0), make_configuration(), None)


def test_invalid_snapshot_schedule_is_rejected_conservatively() -> None:
    state = make_state(reveal_schedule={"quotation": "6 AM"})

    with pytest.raises(SchedulingEvaluationError, match="quotation"):
        evaluate_scheduling(
            datetime(2026, 10, 26, 7, 0, tzinfo=ZoneInfo("America/New_York")),
            make_configuration(),
            state,
        )

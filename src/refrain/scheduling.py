"""Pure evaluation of display-day selection and reveal requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Mapping

from . import local_time
from .config import ApplicationConfiguration
from .persistence import DailySnapshot, PersistentState
from .renderer import CompositionVisibility

_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")


class SchedulingEvaluationError(ValueError):
    """Raised when scheduling inputs cannot be evaluated safely."""


class SchedulingAction(Enum):
    """The action currently required by the scheduling policy."""

    INITIAL_SELECTION = "initial_selection"
    NEW_SELECTION = "new_selection"
    ADVANCE_REVEAL = "advance_reveal"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class SchedulingDecision:
    """An immutable scheduling result for the application coordinator."""

    action: SchedulingAction
    display_date: date | None = None
    required_reveal_stage: int | None = None


def _local_display_date(current_time: datetime, day_start: time) -> date:
    try:
        current_utc = current_time.astimezone(timezone.utc)
        wall_time = local_time.local_wall_time(current_utc)
        boundary = local_time.resolve_local_time(wall_time.date(), day_start)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError("current_time cannot be converted to operating-system local time") from error
    if current_utc >= boundary:
        return wall_time.date()
    try:
        return wall_time.date() - timedelta(days=1)
    except OverflowError as error:
        raise SchedulingEvaluationError("cannot calculate the initial display date") from error


def _schedule_time(schedule: Mapping[str, object], field: str) -> time:
    value = schedule.get(field)
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise SchedulingEvaluationError(f"snapshot reveal schedule.{field} must be a valid HH:MM time")
    return time.fromisoformat(value)


def _resolve_reveal_stages(
    snapshot: DailySnapshot,
) -> tuple[tuple[time, ...], tuple[CompositionVisibility, ...]]:
    if not isinstance(snapshot, DailySnapshot):
        raise SchedulingEvaluationError("snapshot must be a DailySnapshot")
    schedule = snapshot.reveal_schedule
    metadata = snapshot.presentation_metadata
    if not isinstance(schedule, Mapping) or not isinstance(metadata, Mapping):
        raise SchedulingEvaluationError("snapshot reveal schedule and presentation metadata must be mappings")

    quotation_time = _schedule_time(schedule, "quotation")
    day_start = _schedule_time({"day_start": snapshot.scheduling.day_start}, "day_start")
    if quotation_time != day_start:
        raise SchedulingEvaluationError("snapshot reveal schedule.quotation must match snapshot scheduling.day_start")

    field_times = {"quotation": quotation_time}
    for field in ("source", "attribution"):
        value = metadata.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise SchedulingEvaluationError(f"snapshot presentation_metadata.{field} must be a nonempty string")
        event_time = _schedule_time(schedule, field)
        if event_time < quotation_time:
            raise SchedulingEvaluationError(f"snapshot reveal schedule.{field} must not precede quotation")
        field_times[field] = event_time

    event_times = tuple(sorted(set(field_times.values())))
    stages = tuple(
        CompositionVisibility(
            quotation=True,
            source="source" in field_times and field_times["source"] <= event_time,
            attribution="attribution" in field_times and field_times["attribution"] <= event_time,
        )
        for event_time in event_times
    )
    return event_times, stages


def resolve_reveal_stages(snapshot: DailySnapshot) -> tuple[CompositionVisibility, ...]:
    """Return the complete ordered cumulative reveal stages for a snapshot.

    The returned sequence is canonical for both scheduling evaluation and
    preparation/recovery. Fields revealed together share a stage, and fields
    scheduled at the quotation time appear in the initial stage.
    """
    return _resolve_reveal_stages(snapshot)[1]


def _required_stage(state: PersistentState, current_time: datetime) -> int:
    snapshot = state.snapshot
    event_times, stages = _resolve_reveal_stages(snapshot)
    try:
        current_utc = current_time.astimezone(timezone.utc)
        wall_time = local_time.local_wall_time(current_utc)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError("current_time cannot be converted to operating-system local time") from error
    if wall_time.date() > snapshot.display_date:
        clock_stage = len(stages) - 1
    elif wall_time.date() < snapshot.display_date:
        clock_stage = 0
    else:
        try:
            clock_stage = max(
                (
                    index
                    for index, event_time in enumerate(event_times)
                    if local_time.resolve_local_time(snapshot.display_date, event_time) <= current_utc
                ),
                default=0,
            )
        except (OverflowError, OSError, ValueError) as error:
            raise SchedulingEvaluationError("cannot resolve a local reveal deadline") from error

    highest_stage = state.highest_reveal_stage
    if type(highest_stage) is not int or highest_stage < 0:
        raise SchedulingEvaluationError("highest_reveal_stage must be a nonnegative integer")
    if highest_stage >= len(stages):
        raise SchedulingEvaluationError(
            f"highest_reveal_stage {highest_stage} exceeds the last available reveal stage {len(stages) - 1}"
        )
    return max(clock_stage, highest_stage)


def evaluate_scheduling(
    current_time: datetime,
    configuration: ApplicationConfiguration,
    state: PersistentState | None,
) -> SchedulingDecision:
    """Evaluate scheduling requirements without changing state or performing I/O."""
    if not isinstance(current_time, datetime) or current_time.tzinfo is None:
        raise SchedulingEvaluationError("current_time must be timezone-aware")
    try:
        if current_time.utcoffset() is None:
            raise SchedulingEvaluationError("current_time must be timezone-aware")
    except (OverflowError, TypeError, ValueError) as error:
        raise SchedulingEvaluationError("current_time must be timezone-aware") from error
    if not isinstance(configuration, ApplicationConfiguration):
        raise SchedulingEvaluationError("configuration must be an ApplicationConfiguration")
    if (
        not isinstance(configuration.day_start, time)
        or configuration.day_start.tzinfo is not None
        or configuration.day_start.second
        or configuration.day_start.microsecond
    ):
        raise SchedulingEvaluationError("configuration day_start must be a valid HH:MM local time")
    if state is not None and not isinstance(state, PersistentState):
        raise SchedulingEvaluationError("state must be a PersistentState or None")
    if state is not None and (type(state.revision) is not int or state.revision < 1):
        raise SchedulingEvaluationError("state revision must be a positive integer")

    if state is None:
        display_date = _local_display_date(current_time, configuration.day_start)
        return SchedulingDecision(SchedulingAction.INITIAL_SELECTION, display_date=display_date)

    display_date = _local_display_date(current_time, configuration.day_start)
    if display_date != state.snapshot.display_date:
        return SchedulingDecision(SchedulingAction.NEW_SELECTION, display_date=display_date)

    required_stage = _required_stage(state, current_time)
    action = (
        SchedulingAction.ADVANCE_REVEAL if required_stage > state.highest_reveal_stage else SchedulingAction.NO_ACTION
    )
    return SchedulingDecision(action, required_reveal_stage=required_stage)

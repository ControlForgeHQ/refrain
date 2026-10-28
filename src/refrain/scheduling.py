"""Pure evaluation of display-day selection and reveal requirements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import ApplicationConfiguration
from .persistence import PersistentState

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
class DisplayDayBoundary:
    """A boundary observed by the runtime for the specified selection revision.

    ``state_revision`` is the committed selection revision active when the
    boundary was observed. Once that selection is replaced, the observation is
    stale and cannot authorize another selection.
    """

    display_date: date
    state_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.display_date, date) or isinstance(self.display_date, datetime):
            raise ValueError("display_date must be a date")
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise ValueError("state_revision must be a nonnegative integer")


@dataclass(frozen=True)
class SchedulingDecision:
    """An immutable scheduling result for the application coordinator."""

    action: SchedulingAction
    display_date: date | None = None
    required_reveal_stage: int | None = None


def _local_display_date(current_time: datetime, timezone: ZoneInfo, day_start: time) -> date:
    try:
        local_time = current_time.astimezone(timezone)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError("current_time cannot be converted to the configured timezone") from error
    if local_time.timetz().replace(tzinfo=None) >= day_start:
        return local_time.date()
    try:
        return local_time.date() - timedelta(days=1)
    except OverflowError as error:
        raise SchedulingEvaluationError("cannot calculate the initial display date") from error


def _schedule_time(schedule: Mapping[str, object], field: str) -> time:
    value = schedule.get(field)
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise SchedulingEvaluationError(f"snapshot reveal schedule.{field} must be a valid HH:MM time")
    return time.fromisoformat(value)


def _required_stage(state: PersistentState, current_time: datetime) -> int:
    snapshot = state.snapshot
    try:
        timezone = ZoneInfo(snapshot.scheduling.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as error:
        raise SchedulingEvaluationError("snapshot scheduling timezone must be a valid IANA timezone") from error

    schedule = snapshot.reveal_schedule
    metadata = snapshot.presentation_metadata
    if not isinstance(schedule, Mapping) or not isinstance(metadata, Mapping):
        raise SchedulingEvaluationError("snapshot reveal schedule and presentation metadata must be mappings")

    quotation_time = _schedule_time(schedule, "quotation")
    day_start = _schedule_time({"day_start": snapshot.scheduling.day_start}, "day_start")
    if quotation_time != day_start:
        raise SchedulingEvaluationError("snapshot reveal schedule.quotation must match snapshot scheduling.day_start")

    events = {quotation_time}
    for field in ("source", "attribution"):
        value = metadata.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise SchedulingEvaluationError(f"snapshot presentation_metadata.{field} must be a nonempty string")
        event_time = _schedule_time(schedule, field)
        if event_time < quotation_time:
            raise SchedulingEvaluationError(f"snapshot reveal schedule.{field} must not precede quotation")
        events.add(event_time)

    try:
        local_time = current_time.astimezone(timezone)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError("current_time cannot be converted to the snapshot timezone") from error
    event_times = sorted(events)
    if local_time.date() > snapshot.display_date:
        clock_stage = len(event_times) - 1
    elif local_time.date() < snapshot.display_date:
        clock_stage = 0
    else:
        clock_stage = max(
            (
                index
                for index, event_time in enumerate(event_times)
                if event_time <= local_time.timetz().replace(tzinfo=None)
            ),
            default=0,
        )

    highest_stage = state.highest_reveal_stage
    if type(highest_stage) is not int or highest_stage < 0:
        raise SchedulingEvaluationError("highest_reveal_stage must be a nonnegative integer")
    return max(clock_stage, highest_stage)


def evaluate_scheduling(
    current_time: datetime,
    configuration: ApplicationConfiguration,
    state: PersistentState | None,
    observed_boundary: DisplayDayBoundary | None = None,
) -> SchedulingDecision:
    """Evaluate scheduling requirements without changing state or performing I/O.

    An observed boundary is accepted only for the selection revision that was
    current when the runtime observed it. Without a matching observation, a
    display-date mismatch never invalidates committed state.
    """
    if not isinstance(current_time, datetime) or current_time.tzinfo is None:
        raise SchedulingEvaluationError("current_time must be timezone-aware")
    try:
        if current_time.utcoffset() is None:
            raise SchedulingEvaluationError("current_time must be timezone-aware")
    except (OverflowError, TypeError, ValueError) as error:
        raise SchedulingEvaluationError("current_time must be timezone-aware") from error
    if not isinstance(configuration, ApplicationConfiguration):
        raise SchedulingEvaluationError("configuration must be an ApplicationConfiguration")
    if not isinstance(configuration.timezone, ZoneInfo):
        raise SchedulingEvaluationError("configuration timezone must be a valid IANA timezone")
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
    if observed_boundary is not None and not isinstance(observed_boundary, DisplayDayBoundary):
        raise SchedulingEvaluationError("observed_boundary must be a DisplayDayBoundary or None")

    if state is None:
        display_date = _local_display_date(current_time, configuration.timezone, configuration.day_start)
        return SchedulingDecision(SchedulingAction.INITIAL_SELECTION, display_date=display_date)

    if observed_boundary is not None and observed_boundary.state_revision == state.revision:
        return SchedulingDecision(SchedulingAction.NEW_SELECTION, display_date=observed_boundary.display_date)

    required_stage = _required_stage(state, current_time)
    action = (
        SchedulingAction.ADVANCE_REVEAL if required_stage > state.highest_reveal_stage else SchedulingAction.NO_ACTION
    )
    return SchedulingDecision(action, required_reveal_stage=required_stage)

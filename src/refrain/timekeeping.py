"""Hardware-independent observation and waiting for scheduling events."""

from __future__ import annotations

import math
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from threading import Event
from typing import Callable

from . import local_time
from .config import ApplicationConfiguration
from .persistence import PersistentState
from .scheduling import (
    DisplayDayBoundary,
    SchedulingEvaluationError,
    _local_display_date,
    _required_stage,
    _resolve_reveal_stages,
)

_CLOCK_ADJUSTMENT_TOLERANCE = 1.0
_DEFAULT_MAX_CLOCK_CHECK_INTERVAL = 300.0


def _validate_timekeeping_inputs(current_time: datetime, configuration: ApplicationConfiguration) -> datetime:
    if not isinstance(current_time, datetime) or current_time.tzinfo is None:
        raise SchedulingEvaluationError("current_time must be timezone-aware")
    try:
        if current_time.utcoffset() is None:
            raise SchedulingEvaluationError("current_time must be timezone-aware")
        current_utc = current_time.astimezone(timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError) as error:
        raise SchedulingEvaluationError("current_time cannot be converted to UTC") from error
    _validate_configuration(configuration)
    return current_utc


def _validate_configuration(configuration: ApplicationConfiguration) -> None:
    if not isinstance(configuration, ApplicationConfiguration):
        raise SchedulingEvaluationError("configuration must be an ApplicationConfiguration")
    if (
        not isinstance(configuration.day_start, time)
        or configuration.day_start.tzinfo is not None
        or configuration.day_start.second
        or configuration.day_start.microsecond
    ):
        raise SchedulingEvaluationError("configuration day_start must be a valid HH:MM local time")


def _local_datetime(day: date, wall_time: time) -> datetime:
    """Resolve a local wall time to its first occurrence or first valid time after a gap."""
    try:
        return local_time.resolve_local_time(day, wall_time)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError(f"cannot resolve local scheduling time {day} {wall_time}") from error


def next_scheduling_deadline(
    current_time: datetime,
    configuration: ApplicationConfiguration,
    state: PersistentState | None,
) -> datetime:
    """Return the next reveal or configured display-day deadline.

    The returned instant is UTC-aware. Reveal times come from the committed
    snapshot; the next boundary comes from the active application configuration.
    If selection or reveal work is already due, current time is returned for
    immediate evaluation.
    """
    current_utc = _validate_timekeeping_inputs(current_time, configuration)
    if state is None:
        return current_utc
    try:
        display_date = _local_display_date(current_utc, configuration.day_start)
        boundary_date = display_date + timedelta(days=1)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError("cannot calculate the next display-day boundary") from error

    try:
        boundary_deadline = _local_datetime(boundary_date, configuration.day_start)
        while boundary_deadline <= current_utc:
            boundary_date += timedelta(days=1)
            boundary_deadline = _local_datetime(boundary_date, configuration.day_start)
    except (OverflowError, OSError, ValueError) as error:
        raise SchedulingEvaluationError("cannot calculate the next display-day boundary") from error
    deadlines = [boundary_deadline]
    if state is not None:
        if not isinstance(state, PersistentState):
            raise SchedulingEvaluationError("state must be a PersistentState or None")
        required_stage = _required_stage(state, current_utc)
        if required_stage > state.highest_reveal_stage:
            return current_utc
        event_times, _ = _resolve_reveal_stages(state.snapshot)
        try:
            for stage_index, event_time in enumerate(event_times):
                if stage_index <= state.highest_reveal_stage:
                    continue
                reveal_deadline = _local_datetime(state.snapshot.display_date, event_time)
                if reveal_deadline > current_utc:
                    deadlines.append(reveal_deadline)
        except (OverflowError, OSError, ValueError) as error:
            raise SchedulingEvaluationError("cannot calculate the next reveal deadline") from error

    return min(deadlines)


class DisplayDayBoundaryObserver:
    """Recognize boundaries crossed while this process continuously observes time.

    The first observation establishes a baseline only. Clock discontinuities
    backward reset that baseline without creating a boundary; an existing
    pending boundary remains available while its selection revision is current.
    Forward jumps produce at most one observation for the currently appropriate
    date.
    """

    def __init__(self, configuration: ApplicationConfiguration) -> None:
        _validate_configuration(configuration)
        self._configuration = configuration
        self._previous_wall_utc: datetime | None = None
        self._previous_local_wall: datetime | None = None
        self._previous_monotonic: float | None = None
        self._previous_display_date: date | None = None
        self._pending_boundary: DisplayDayBoundary | None = None
        self._last_boundary_date: date | None = None

    def observe(
        self,
        current_time: datetime,
        monotonic_time: float,
        state_revision: int | None,
    ) -> DisplayDayBoundary | None:
        """Return one revision-bound boundary when continuously observed.

        ``state_revision`` is the committed selection revision at this
        observation. ``None`` is appropriate before the initial selection;
        startup never infers a historical boundary from its first timestamp.
        """
        current_utc = _validate_timekeeping_inputs(current_time, self._configuration)
        if isinstance(monotonic_time, bool) or not isinstance(monotonic_time, (int, float)):
            raise ValueError("monotonic_time must be a finite number")
        if not math.isfinite(monotonic_time) or monotonic_time < 0:
            raise ValueError("monotonic_time must be a finite nonnegative number")
        if state_revision is not None and (type(state_revision) is not int or state_revision < 0):
            raise ValueError("state_revision must be a nonnegative integer or None")

        display_date = _local_display_date(current_utc, self._configuration.day_start)
        try:
            local_wall = local_time.local_wall_time(current_utc)
        except (OverflowError, OSError, ValueError) as error:
            raise SchedulingEvaluationError("current_time cannot be converted to operating-system local time") from error
        previous_wall_utc = self._previous_wall_utc
        previous_local_wall = self._previous_local_wall
        previous_monotonic = self._previous_monotonic
        previous_display_date = self._previous_display_date
        if (
            previous_wall_utc is None
            or previous_local_wall is None
            or previous_monotonic is None
            or previous_display_date is None
        ):
            self._record(current_utc, local_wall, monotonic_time, display_date)
            return None

        elapsed_monotonic = monotonic_time - previous_monotonic
        if elapsed_monotonic < 0:
            raise ValueError("monotonic_time must not move backward")
        elapsed_wall = (current_utc - previous_wall_utc).total_seconds()
        backward_adjustment = elapsed_wall < elapsed_monotonic - _CLOCK_ADJUSTMENT_TOLERANCE
        local_rules_changed = local_time.local_wall_time(previous_wall_utc) != previous_local_wall
        self._record(current_utc, local_wall, monotonic_time, display_date)

        if self._pending_boundary is not None:
            if self._pending_boundary.state_revision == state_revision:
                if (
                    not local_rules_changed
                    and not backward_adjustment
                    and display_date > previous_display_date
                    and display_date > self._pending_boundary.display_date
                ):
                    self._pending_boundary = DisplayDayBoundary(display_date, state_revision)
                return self._pending_boundary
            self._last_boundary_date = self._pending_boundary.display_date
            self._pending_boundary = None

        if backward_adjustment or local_rules_changed:
            self._last_boundary_date = None
            return None
        if state_revision is None or display_date <= previous_display_date:
            return None
        if display_date == self._last_boundary_date:
            return None

        self._pending_boundary = DisplayDayBoundary(display_date, state_revision)
        return self._pending_boundary

    def _record(self, wall_utc: datetime, local_wall: datetime, monotonic: float, display_date: date) -> None:
        self._previous_wall_utc = wall_utc
        self._previous_local_wall = local_wall
        self._previous_monotonic = monotonic
        self._previous_display_date = display_date


def wait_for_scheduling_event(
    deadline: datetime,
    wake_event: Event,
    *,
    wall_clock: Callable[[], datetime] | None = None,
    monotonic_clock: Callable[[], float] = time_module.monotonic,
    max_clock_check_interval: float = _DEFAULT_MAX_CLOCK_CHECK_INTERVAL,
) -> bool:
    """Wait for a scheduling deadline or an external wake event.

    Returns ``True`` when the event is set and ``False`` when the deadline is
    due or the wall clock changes enough to require scheduling reevaluation.
    Clock changes are checked at a bounded interval without busy waiting.
    """
    if not isinstance(deadline, datetime) or deadline.tzinfo is None:
        raise ValueError("deadline must be timezone-aware")
    if not callable(getattr(wake_event, "is_set", None)) or not callable(getattr(wake_event, "wait", None)):
        raise ValueError("wake_event must provide is_set() and wait(timeout)")
    if not callable(wall_clock) and wall_clock is not None:
        raise ValueError("wall_clock must be callable")
    if not callable(monotonic_clock):
        raise ValueError("monotonic_clock must be callable")
    if (
        isinstance(max_clock_check_interval, bool)
        or not isinstance(max_clock_check_interval, (int, float))
        or not math.isfinite(max_clock_check_interval)
        or max_clock_check_interval <= 0
    ):
        raise ValueError("max_clock_check_interval must be a finite positive number")

    read_wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
    deadline_utc = _validate_deadline_clock(deadline)
    while True:
        current_time = read_wall_clock()
        current_utc = _validate_deadline_clock(current_time)
        if wake_event.is_set():
            return True
        remaining = (deadline_utc - current_utc).total_seconds()
        if remaining <= 0:
            return False

        before_monotonic = monotonic_clock()
        if isinstance(before_monotonic, bool) or not isinstance(before_monotonic, (int, float)):
            raise ValueError("monotonic_clock must return a finite number")
        if not math.isfinite(before_monotonic):
            raise ValueError("monotonic_clock must return a finite number")
        if wake_event.wait(min(remaining, max_clock_check_interval)):
            return True

        after_time = _validate_deadline_clock(read_wall_clock())
        after_monotonic = monotonic_clock()
        if isinstance(after_monotonic, bool) or not isinstance(after_monotonic, (int, float)):
            raise ValueError("monotonic_clock must return a finite number")
        if not math.isfinite(after_monotonic) or after_monotonic < before_monotonic:
            raise ValueError("monotonic_clock must return finite nondecreasing values")
        wall_elapsed = (after_time - current_utc).total_seconds()
        monotonic_elapsed = after_monotonic - before_monotonic
        if abs(wall_elapsed - monotonic_elapsed) > _CLOCK_ADJUSTMENT_TOLERANCE:
            return False


def _validate_deadline_clock(current_time: datetime) -> datetime:
    if not isinstance(current_time, datetime) or current_time.tzinfo is None:
        raise ValueError("wall_clock must return a timezone-aware datetime")
    try:
        if current_time.utcoffset() is None:
            raise ValueError("wall_clock must return a timezone-aware datetime")
        return current_time.astimezone(timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError) as error:
        raise ValueError("wall_clock returned a datetime that cannot be converted to UTC") from error

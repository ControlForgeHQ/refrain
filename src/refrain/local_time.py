"""Operating-system local civil-time conversion."""

from __future__ import annotations

import time as time_module
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable


@dataclass(frozen=True)
class LocalTimeRules:
    """Convert between absolute instants and host-local wall times."""

    localtime: Callable[[float], time_module.struct_time] = field(default=time_module.localtime)
    mktime: Callable[[tuple[int, ...]], float] = field(default=time_module.mktime)

    def wall_time(self, instant: datetime) -> datetime:
        timestamp = instant.timestamp()
        local = self.localtime(timestamp)
        return datetime(
            local.tm_year,
            local.tm_mon,
            local.tm_mday,
            local.tm_hour,
            local.tm_min,
            local.tm_sec,
            instant.microsecond,
        )

    def resolve(self, day: date, wall_time: time) -> datetime:
        """Resolve a wall time to its first occurrence or first valid time after a gap."""
        wall = datetime.combine(day, wall_time)

        def exact_candidates(value: datetime) -> list[float]:
            candidates = []
            for is_dst in (0, 1):
                timestamp = self.mktime(
                    (value.year, value.month, value.day, value.hour, value.minute, value.second, -1, -1, is_dst)
                )
                local = self.localtime(timestamp)
                if (
                    local.tm_year,
                    local.tm_mon,
                    local.tm_mday,
                    local.tm_hour,
                    local.tm_min,
                    local.tm_sec,
                ) == (value.year, value.month, value.day, value.hour, value.minute, value.second):
                    candidates.append(timestamp)
            return candidates

        for offset in range(0, 172801, 60):
            if exact_candidates(wall + timedelta(seconds=offset)):
                for adjustment in range(max(0, offset - 59), offset + 1):
                    candidates = exact_candidates(wall + timedelta(seconds=adjustment))
                    if candidates:
                        return datetime.fromtimestamp(min(candidates), timezone.utc)

        raise ValueError(f"cannot resolve local scheduling time {wall!s}")


SYSTEM_LOCAL_TIME = LocalTimeRules()


def local_wall_time(instant: datetime) -> datetime:
    """Return the host-local wall time for an absolute instant."""
    return SYSTEM_LOCAL_TIME.wall_time(instant)


def resolve_local_time(day: date, wall_time: time) -> datetime:
    """Return a UTC-aware instant for a host-local wall time."""
    return SYSTEM_LOCAL_TIME.resolve(day, wall_time)

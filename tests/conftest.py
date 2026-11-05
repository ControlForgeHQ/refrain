from __future__ import annotations

import time as time_module
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import pytest

import refrain.local_time as local_time


@pytest.fixture
def set_local_timezone(monkeypatch: pytest.MonkeyPatch):
    def install(zone: tzinfo) -> None:
        def localtime(timestamp: float) -> time_module.struct_time:
            local = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(zone)
            is_dst = int(local.dst() is not None and local.dst() != timedelta(0))
            return time_module.struct_time(
                (
                    local.year,
                    local.month,
                    local.day,
                    local.hour,
                    local.minute,
                    local.second,
                    local.weekday(),
                    local.timetuple().tm_yday,
                    is_dst,
                )
            )

        def mktime(value: tuple[int, ...]) -> float:
            local = datetime(*value[:6], tzinfo=zone, fold=0 if value[8] else 1)
            return local.timestamp()

        monkeypatch.setattr(local_time, "SYSTEM_LOCAL_TIME", local_time.LocalTimeRules(localtime, mktime))

    return install


@pytest.fixture(autouse=True)
def new_york_local_timezone(set_local_timezone) -> None:
    set_local_timezone(ZoneInfo("America/New_York"))

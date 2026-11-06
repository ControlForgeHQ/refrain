from __future__ import annotations

import errno
import subprocess
import sys
import time as time_module
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import refrain.local_time as local_time


@pytest.fixture
def symlink_or_skip():
    def create(link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except NotImplementedError as error:
            pytest.skip(f"symbolic links are unsupported: {error}")
        except OSError as error:
            unavailable_errors = {
                errno.EACCES,
                errno.EPERM,
                getattr(errno, "ENOSYS", -1),
                getattr(errno, "ENOTSUP", -1),
                getattr(errno, "EOPNOTSUPP", -1),
            }
            if error.errno in unavailable_errors or getattr(error, "winerror", None) == 1314:
                pytest.skip(f"symbolic-link creation is unavailable or denied: {error}")
            raise

    return create


@pytest.fixture
def junction_or_skip():
    def create(link: Path, target: Path) -> None:
        if sys.platform != "win32":
            pytest.skip("Windows junctions are platform-specific")
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise OSError(
                f"could not create Windows junction {link} -> {target}: "
                f"{result.stdout.strip()} {result.stderr.strip()}"
            )
        if not link.is_junction():
            raise AssertionError(f"junction command did not create a junction at {link}")

    return create


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

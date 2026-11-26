"""Filesystem object checks used during discovery."""

import stat
from pathlib import Path


def is_redirected(path: Path) -> bool:
    status = path.lstat()
    return stat.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )

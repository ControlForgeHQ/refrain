from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

_ROOT = Path(__file__).parent.parent
_LIBRARIES = {f"DEV_Config_{bits}_{variant}.so" for bits in ("32", "64") for variant in ("b", "w")}


def _copy_build_tree(project: Path) -> Path:
    source = project / "source"
    shutil.copytree(
        _ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    vendor = source / "src/refrain/display/vendor/waveshare"
    for filename in _LIBRARIES:
        (vendor / filename).write_bytes(b"locally supplied native library placeholder")
    return source


def test_wheel_and_sdist_exclude_external_native_libraries(tmp_path: Path) -> None:
    source = _copy_build_tree(tmp_path)
    wheel_dir = tmp_path / "wheel"
    sdist_dir = tmp_path / "sdist"
    wheel_dir.mkdir()
    sdist_dir.mkdir()
    env = os.environ.copy()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--ignore-requires-python",
            str(source),
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=source,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(tmp_path / "build-backend"),
            "setuptools>=80.9.0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    env["PYTHONPATH"] = str(tmp_path / "build-backend")
    subprocess.run(
        [
            sys.executable,
            "-c",
            ("from setuptools.build_meta import build_sdist; " f"build_sdist({str(sdist_dir)!r})"),
        ],
        cwd=source,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = next(wheel_dir.glob("*.whl"))
    sdist = next(sdist_dir.glob("*.tar.gz"))
    with ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    with tarfile.open(sdist) as archive:
        sdist_names = archive.getnames()

    assert not any(Path(name).name in _LIBRARIES for name in wheel_names)
    assert not any(Path(name).name in _LIBRARIES for name in sdist_names)
    assert any(name.endswith("display/vendor/waveshare/README.md") for name in wheel_names)
    assert any(name.endswith("display/vendor/waveshare/README.md") for name in sdist_names)

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
from configparser import ConfigParser
from email.parser import BytesParser
from pathlib import Path
from textwrap import dedent
from zipfile import ZipFile

import yaml

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
    version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert wheel.name == f"controlforge_refrain-{version}-py3-none-any.whl"
    assert sdist.name == f"controlforge_refrain-{version}.tar.gz"
    with ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
        wheel_metadata = archive.read(f"controlforge_refrain-{version}.dist-info/METADATA")
        wheel_entry_points = archive.read(f"controlforge_refrain-{version}.dist-info/entry_points.txt")
    with tarfile.open(sdist) as archive:
        sdist_names = archive.getnames()
        sdist_metadata = archive.extractfile(f"controlforge_refrain-{version}/PKG-INFO").read()
        sdist_entry_points = archive.extractfile(
            f"controlforge_refrain-{version}/src/controlforge_refrain.egg-info/entry_points.txt"
        ).read()

    for metadata in (wheel_metadata, sdist_metadata):
        headers = BytesParser().parsebytes(metadata)
        assert headers["Name"] == "controlforge-refrain"
        assert headers["Version"] == version
    for entry_points in (wheel_entry_points, sdist_entry_points):
        entries = ConfigParser()
        entries.read_string(entry_points.decode("utf-8"))
        assert dict(entries["console_scripts"]) == {
            "refrain": "refrain.__main__:main",
            "refrain-viewer": "refrain.viewer:main",
        }

    assert not any(Path(name).name in _LIBRARIES for name in wheel_names)
    assert not any(Path(name).name in _LIBRARIES for name in sdist_names)
    assert any(name.endswith("display/vendor/waveshare/README.md") for name in wheel_names)
    assert any(name.endswith("display/vendor/waveshare/README.md") for name in sdist_names)
    assert any(name.endswith("assets/branding/controlforge-logo.png") for name in wheel_names)
    assert any(name.endswith("assets/branding/refrain-logo.png") for name in wheel_names)
    assert any(name.endswith("assets/branding/controlforge-logo.png") for name in sdist_names)
    assert any(name.endswith("assets/branding/refrain-logo.png") for name in sdist_names)
    for package in (wheel_names, sdist_names):
        assert any(name.endswith("systemd/refrain.service") for name in package)
        assert any(name.endswith("config.default.yaml") for name in package)
        assert any(name.endswith("sample_content/shakespeare-hamlet.yaml") for name in package)
        assert any(name.endswith("sample_content/shakespeare-as-you-like-it.yaml") for name in package)
        assert any(name.endswith("sample_content/shakespeare-king-lear.yaml") for name in package)
    for names, package_root in (
        (wheel_names, "refrain"),
        (sdist_names, f"controlforge_refrain-{version}/src/refrain"),
    ):
        prefix = f"{package_root}/"
        packaged_files = {name[len(prefix) :] for name in names if name.startswith(prefix)}
        assert "assets/README.md" in packaged_files
        for category in ("fonts", "backgrounds", "decorations"):
            expected_files = {
                path.relative_to(source / "src" / "refrain").as_posix()
                for path in (source / "src" / "refrain" / "assets" / category).rglob("*")
                if path.is_file()
            }
            assert expected_files <= packaged_files
        font_root = source / "src" / "refrain" / "assets" / "fonts"
        for font_package in sorted(font_root.iterdir()):
            manifest = yaml.safe_load((font_package / "font.yaml").read_text(encoding="utf-8"))
            package_path = Path("assets/fonts") / font_package.name
            for filename in (*manifest["faces"].values(), "font.yaml", "OFL.txt"):
                assert (package_path / filename).as_posix() in packaged_files

    installed = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--ignore-requires-python",
            "--target",
            str(installed),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    env["PYTHONPATH"] = str(installed)
    subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""
                from importlib.resources import files
                from importlib.metadata import version
                from pathlib import Path
                from PIL import ImageFont
                from tempfile import TemporaryDirectory
                from refrain.config import (
                    load_application_config,
                    load_background_image,
                    load_composition_layer_image,
                    load_decoration_layer_image,
                )
                from refrain.content import load_content_library
                from refrain.installation import initialize_installation
                from refrain.paths import ApplicationPaths
                from refrain.information_view import _application_version

                assert _application_version() == version("controlforge-refrain")
                root = files("refrain")
                assert root.joinpath("systemd", "refrain.service").is_file()
                assert root.joinpath("assets", "branding", "controlforge-logo.png").is_file()
                assert root.joinpath("config.default.yaml").is_file()
                assert root.joinpath("sample_content", "shakespeare-hamlet.yaml").is_file()
                assert root.joinpath("assets", "README.md").read_text(encoding="utf-8")
                with TemporaryDirectory() as temporary:
                    base = Path(temporary)
                    config = base / "config" / "refrain"
                    state = base / "state" / "refrain"
                    cache = base / "cache" / "refrain"
                    paths = ApplicationPaths(
                        config, config / "config.yaml", config / "content", state, state,
                        state / "state.json", state / "global-history.jsonl", cache, cache / "artifacts"
                    )
                    initialize_installation(paths)
                    loaded = load_application_config(paths.config_file)
                    assert loaded.content_directory == paths.content_directory
                    assert set(loaded.default_backgrounds) <= set(loaded.backgrounds) | {"none"}
                    assert len(load_content_library(paths.content_directory)) >= 3
                    for resource in loaded.fonts.values():
                        assert resource.bundled
                        assert resource.path.parent.joinpath("OFL.txt").is_file()
                        for face in resource.faces.values():
                            with face.open("rb") as stream:
                                ImageFont.truetype(stream, size=12)
                    for resource in loaded.backgrounds.values():
                        assert resource.bundled
                        images = (
                            [load_background_image(resource)]
                            if resource.path is not None
                            else [load_composition_layer_image(layer) for layer in resource.layers]
                        )
                        for image in images:
                            assert image.format == "PNG"
                            assert image.width > 0 and image.height > 0
                            assert image.mode in ("RGB", "RGBA")
                            image.close()
                    for resource in loaded.decorations.values():
                        assert resource.bundled
                        for layer in resource.layers:
                            image = load_decoration_layer_image(layer)
                            assert image.format == "PNG"
                            assert image.width > 0 and image.height > 0
                            assert image.mode in ("RGB", "RGBA")
                            image.close()
                """),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

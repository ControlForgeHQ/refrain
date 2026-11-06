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
_BACKGROUNDS = ("aged-paper", "canvas", "cloth", "ethereal", "hex")
_DECORATIONS = ("ethereal", "hex", "lower-flourish", "simple-border", "top-bottom-borders")


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
    assert any(name.endswith("assets/branding/controlforge-logo.png") for name in wheel_names)
    assert any(name.endswith("assets/branding/refrain-logo.png") for name in wheel_names)
    assert any(name.endswith("assets/fonts/alegreya/Alegreya-Regular.ttf") for name in wheel_names)
    assert any(name.endswith("assets/fonts/alegreya/OFL.txt") for name in wheel_names)
    assert any(name.endswith("assets/fonts/orbitron/Orbitron-Regular.ttf") for name in wheel_names)
    assert any(name.endswith("assets/fonts/orbitron/OFL.txt") for name in wheel_names)
    assert any(name.endswith("assets/branding/controlforge-logo.png") for name in sdist_names)
    assert any(name.endswith("assets/branding/refrain-logo.png") for name in sdist_names)
    assert any(name.endswith("assets/fonts/alegreya/Alegreya-Regular.ttf") for name in sdist_names)
    assert any(name.endswith("assets/fonts/alegreya/OFL.txt") for name in sdist_names)
    assert any(name.endswith("assets/fonts/orbitron/Orbitron-Regular.ttf") for name in sdist_names)
    assert any(name.endswith("assets/fonts/orbitron/OFL.txt") for name in sdist_names)
    for package in (wheel_names, sdist_names):
        assert any(name.endswith("config.default.yaml") for name in package)
        assert any(name.endswith("sample_content/shakespeare-hamlet.yaml") for name in package)
        assert any(name.endswith("sample_content/shakespeare-as-you-like-it.yaml") for name in package)
        assert any(name.endswith("sample_content/shakespeare-king-lear.yaml") for name in package)
    for names in (wheel_names, sdist_names):
        assert any(name.endswith("assets/README.md") for name in names)
        for identifier in _BACKGROUNDS:
            assert any(name.endswith(f"assets/backgrounds/{identifier}.png") for name in names)
        for identifier in _DECORATIONS:
            assert any(name.endswith(f"assets/decorations/{identifier}.png") for name in names)

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
            (
                "from importlib.resources import files; "
                "from pathlib import Path; "
                "from PIL import Image; "
                "from tempfile import TemporaryDirectory; "
                "from refrain import DecorationResource, load_decoration_image; "
                "from refrain.config import load_application_config; "
                "from refrain.content import load_content_library; "
                "from refrain.installation import initialize_installation; "
                "from refrain.paths import ApplicationPaths; "
                "root=files('refrain'); "
                "assert root.joinpath('assets','branding','controlforge-logo.png').is_file(); "
                "assert root.joinpath('config.default.yaml').is_file(); "
                "assert root.joinpath('sample_content','shakespeare-hamlet.yaml').is_file(); "
                "assert root.joinpath('assets','fonts','orbitron','Orbitron-Regular.ttf').is_file(); "
                "assert root.joinpath('assets','fonts','orbitron','OFL.txt').is_file(); "
                "assert root.joinpath('assets','README.md').read_text(encoding='utf-8'); "
                "resource=root.joinpath('assets','backgrounds','aged-paper.png'); "
                "stream=resource.open('rb'); "
                "image=Image.open(stream); "
                "assert image.format == 'PNG'; "
                "assert image.size == (1600,1200); "
                "assert image.mode in ('RGB','RGBA'); "
                "assert image.n_frames == 1; "
                "image.load(); "
                "assert isinstance(image.getpixel((0,0)),tuple); "
                "image.close(); "
                "stream.close(); "
                "identifiers=('ethereal','hex','lower-flourish','simple-border','top-bottom-borders'); "
                "resources=[DecorationResource(name,root.joinpath('assets','decorations',name+'.png'),True) "
                "for name in identifiers]; "
                "images=[load_decoration_image(resource) for resource in resources]; "
                "assert all(image.mode == 'RGBA' and image.size == (1600,1200) for image in images); "
                "[image.close() for image in images]; "
                "temporary=TemporaryDirectory(); "
                "base=Path(temporary.name); "
                "config=base/'config'/'refrain'; "
                "state=base/'state'/'refrain'; "
                "cache=base/'cache'/'refrain'; "
                "paths=ApplicationPaths(config,config/'config.yaml',config/'content',state,state,state/'state.json',"
                "state/'global-history.jsonl',cache,cache/'artifacts'); "
                "initialize_installation(paths); "
                "loaded=load_application_config(paths.config_file); "
                "assert loaded.content_directory == paths.content_directory; "
                "assert len(load_content_library(paths.content_directory)) >= 3; "
                "temporary.cleanup()"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

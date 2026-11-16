from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

import yaml
from PIL import ImageFont


def bundled_font_paths() -> tuple[Traversable, ...]:
    """Discover real faces for integration tests without fixing an inventory."""
    root = files("refrain").joinpath("assets", "fonts")
    paths = []

    def collect(package: Traversable) -> None:
        manifest = package.joinpath("font.yaml")
        if manifest.is_file():
            data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            faces = data["faces"]
            paths.append(package.joinpath(faces["regular"]))
            paths.extend(package.joinpath(filename) for name, filename in sorted(faces.items()) if name != "regular")
        else:
            for child in sorted(package.iterdir(), key=lambda item: item.name):
                if child.is_dir():
                    collect(child)

    collect(root)
    assert paths, "the package must supply a usable font"
    return tuple(paths)


def write_font_bundle(directory: Path, identifier: str = "test-font") -> Path:
    """Supply a loadable font independently of Refrain's bundled artwork."""
    directory.mkdir(parents=True, exist_ok=True)
    font = directory / "Regular.ttf"
    font.write_bytes(ImageFont.load_default(size=20).font_bytes)
    (directory / "font.yaml").write_text(
        yaml.safe_dump({"format": 1, "id": identifier, "faces": {"regular": font.name}}),
        encoding="utf-8",
    )
    return font


def write_configuration(path: Path, **settings: object) -> Path:
    write_font_bundle(path.parent / "assets" / "fonts" / "test-font")
    data = {
        "destinations": [{"id": "window", "type": "window", "audience": "private"}],
        "fonts": {
            "pools": {"default": ["test-font"]},
        },
        "text": {"min_font_size": 28, "max_font_size": 100},
        **settings,
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path

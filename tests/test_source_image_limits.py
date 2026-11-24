from __future__ import annotations

import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from PIL import Image

from refrain.assets import discover_backgrounds, discover_decorations
from refrain.config import (
    load_background_image,
    load_composition_layer_image,
    load_decoration_layer_image,
)

LIMIT = 36_864_000


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (2, 2)) as image:
        image.save(path)


def _resources(root: Path, kind: str) -> tuple[dict, list[tuple[str, str, int]]]:
    diagnostics = []

    def report(field: str, message: str, severity: int) -> None:
        diagnostics.append((field, message, severity))

    if kind == "standalone":
        registry = discover_backgrounds(root / "bundled", root / "assets", report)
    elif kind == "background":
        registry = discover_backgrounds(root / "bundled", root / "assets", report)
    else:
        registry = discover_decorations(root / "bundled", root / "assets", set(), set(), report, lambda *_: None)
    return registry, diagnostics


def _make_resource(root: Path, kind: str, identifier: str) -> Path:
    if kind == "standalone":
        path = root / "assets" / f"{identifier}.png"
    else:
        package = root / "assets" / identifier
        path = package / "layer.png"
    _write_png(path)
    if kind != "standalone":
        manifest = {"format": 1, "id": identifier, "layers": [{"image": "layer.png"}]}
        (path.parent / f"{kind}.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return path


def _fake_image(size: tuple[int, int]) -> MagicMock:
    image = MagicMock()
    image.format = "PNG"
    image.mode = "RGB"
    image.width, image.height = size
    image.size = size
    image.n_frames = 1
    image.__enter__.return_value = image
    return image


@pytest.mark.parametrize("kind", ["standalone", "background", "decoration"])
@pytest.mark.parametrize("pixels", [LIMIT - 1, LIMIT, LIMIT + 1])
def test_registration_checks_limit_before_integrity_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, pixels: int
) -> None:
    _make_resource(tmp_path, kind, "candidate")
    _make_resource(tmp_path, kind, "healthy")
    images = []

    def open_image(stream):
        image = _fake_image((pixels, 1) if "candidate" in str(stream.name) else (2, 2))
        images.append((str(stream.name), image))
        return image

    monkeypatch.setattr(Image, "open", open_image)
    registry, diagnostics = _resources(tmp_path, kind)

    assert "healthy" in registry
    assert ("candidate" in registry) is (pixels <= LIMIT)
    candidate = next(image for name, image in images if "candidate" in name)
    assert candidate.verify.call_count == (pixels <= LIMIT)
    candidate.load.assert_not_called()
    if pixels > LIMIT:
        assert any("candidate" in field and "36,864,000" in message for field, message, _ in diagnostics)


@pytest.mark.parametrize("kind", ["standalone", "background", "decoration"])
@pytest.mark.parametrize("pixels", [LIMIT - 1, LIMIT, LIMIT + 1])
def test_preparation_revalidates_current_dimensions_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, pixels: int
) -> None:
    _make_resource(tmp_path, kind, "candidate")
    registry, _ = _resources(tmp_path, kind)
    resource = registry["candidate"]
    if kind == "standalone":
        loaders = [(load_background_image, resource)]
    elif kind == "background":
        loaders = [(load_composition_layer_image, resource.layers[0])]
    else:
        loaders = [
            (load_decoration_layer_image, resource.layers[0]),
            (load_composition_layer_image, resource.layers[0]),
        ]
    for loader, layer in loaders:
        image = _fake_image((pixels, 1))
        monkeypatch.setattr(Image, "open", lambda _stream: image)
        if pixels > LIMIT:
            with pytest.raises(ValueError, match="36,864,000"):
                loader(layer)
            image.load.assert_not_called()
            image.close.assert_called_once()
        else:
            assert loader(layer) is image
            image.load.assert_called_once()


@pytest.mark.parametrize("kind", ["standalone", "background", "decoration"])
def test_real_oversized_png_header_is_rejected_after_registration(tmp_path: Path, kind: str) -> None:
    path = _make_resource(tmp_path, kind, "candidate")
    registry, _ = _resources(tmp_path, kind)
    resource = registry["candidate"]
    data = bytearray(path.read_bytes())
    struct.pack_into(">II", data, 16, 7680, 4801)
    struct.pack_into(">I", data, 29, zlib.crc32(data[12:29]))
    path.write_bytes(data)

    registry_after_change, diagnostics = _resources(tmp_path, kind)
    assert "candidate" not in registry_after_change
    assert any("36,864,000" in message for _, message, _ in diagnostics)
    if kind == "standalone":
        loader, layer = load_background_image, resource
    else:
        loader, layer = load_composition_layer_image, resource.layers[0]
    with pytest.raises(ValueError, match="36,864,000"):
        loader(layer)

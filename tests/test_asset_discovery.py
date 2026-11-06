from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from PIL import Image

from refrain import load_application_config

_BUNDLED_LORA = Path(__file__).parents[1] / "src" / "refrain" / "assets" / "fonts" / "lora" / "Lora-Regular.ttf"


def _config_data(**layout_sections: object) -> dict[str, object]:
    layout: dict[str, object] = {
        "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
        "fonts": {"default": ["lora"]},
        "backgrounds": {"default": ["none"]},
        "decorations": {"default": ["none"]},
        "text": {"min_font_size": 12, "max_font_size": 32},
    }
    layout.update(layout_sections)
    return {"display": {"backends": [{"type": "window"}]}, "layout": layout}


def _write_config(path: Path, data: dict[str, object] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data or _config_data(), sort_keys=False), encoding="utf-8")
    return path


def _write_png(path: Path, mode: str = "RGB", size: tuple[int, int] = (19, 13)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size).save(path)
    return path


def _write_manifest(directory: Path, name: str, data: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_discovers_standalone_and_packaged_backgrounds_without_changing_pool(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets" / "backgrounds"
    _write_png(asset_root / "paper" / "handmade-paper.png", size=(13, 27))
    package = asset_root / "forest"
    _write_png(package / "forest.png", size=(41, 23))
    _write_png(package / "inside.png")
    _write_manifest(package, "background.yaml", {"format": 1, "id": "forest", "image": "forest.png"})

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert {"handmade-paper", "forest"} <= set(config.backgrounds)
    assert "inside" not in config.backgrounds
    assert config.default_backgrounds == ("none",)
    assert config.backgrounds["forest"].path == package / "forest.png"


def test_image_discovery_checks_metadata_without_decoding_or_copying(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "assets"
    _write_png(root / "backgrounds" / "paper.png")
    _write_png(root / "decorations" / "border" / "border.png", "RGBA")
    _write_manifest(
        root / "decorations" / "border",
        "decoration.yaml",
        {"format": 1, "id": "border", "image": "border.png"},
    )

    def reject_decode_or_copy(*args, **kwargs):
        raise AssertionError("discovery must not decode or copy source image pixels")

    monkeypatch.setattr(Image.Image, "load", reject_decode_or_copy)
    monkeypatch.setattr(Image.Image, "copy", reject_decode_or_copy)

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert "paper" in config.backgrounds
    assert "border" in config.decorations


def test_image_loaders_do_not_copy_decoded_source_images(tmp_path: Path, monkeypatch) -> None:
    from refrain.config import (
        BackgroundResource,
        DecorationResource,
        load_background_image,
        load_decoration_image,
    )

    background_path = _write_png(tmp_path / "paper.png")
    decoration_path = _write_png(tmp_path / "border.png", "RGBA")

    def reject_copy(*args, **kwargs):
        raise AssertionError("image loading must not copy the full-resolution source")

    monkeypatch.setattr(Image.Image, "copy", reject_copy)

    with load_background_image(BackgroundResource("paper", background_path, False)) as image:
        assert image.size == (19, 13)
        assert image.mode == "RGB"
    with load_decoration_image(DecorationResource("border", decoration_path, False)) as image:
        assert image.size == (19, 13)
        assert image.mode == "RGBA"


def test_discovers_font_bundles_and_decoration_metadata(tmp_path: Path, caplog) -> None:
    font_dir = tmp_path / "assets" / "fonts" / "literary"
    font_dir.mkdir(parents=True)
    shutil.copyfile(_BUNDLED_LORA, font_dir / "Regular.ttf")
    shutil.copyfile(_BUNDLED_LORA, font_dir / "Script.otf")
    _write_manifest(
        font_dir,
        "font.yaml",
        {
            "format": 1,
            "id": "literary",
            "faces": {"regular": "Regular.ttf", "handwritten": "Script.otf"},
        },
    )
    decoration_dir = tmp_path / "assets" / "decorations" / "botanical"
    _write_png(decoration_dir / "border.png", "RGBA")
    _write_manifest(
        decoration_dir,
        "decoration.yaml",
        {
            "format": 1,
            "id": "botanical-border",
            "image": "border.png",
            "presentation_region": {"x": 0.12, "y": 0.16, "width": 0.76, "height": 0.68},
            "font": "missing-font",
            "background": "missing-background",
        },
    )

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert set(config.fonts["literary"].faces) == {"regular", "handwritten"}
    assert config.fonts["literary"].path == font_dir / "Regular.ttf"
    decoration = config.decorations["botanical-border"]
    assert decoration.presentation_region is not None
    assert decoration.presentation_region.x == 0.12
    assert decoration.font is None
    assert decoration.background is None
    assert config.default_fonts == ("lora",)
    assert config.default_decorations == ("none",)
    assert "font preference 'missing-font' is unavailable" in caplog.text
    assert "background preference 'missing-background' is unavailable" in caplog.text


def test_invalid_optional_font_faces_do_not_exclude_a_bundle(tmp_path: Path, caplog) -> None:
    package = tmp_path / "assets" / "fonts" / "literary"
    package.mkdir(parents=True)
    shutil.copyfile(_BUNDLED_LORA, package / "Regular.ttf")
    (package / "Broken.ttf").write_bytes(b"not a font")
    _write_manifest(
        package,
        "font.yaml",
        {
            "format": 1,
            "id": "literary",
            "faces": {
                "regular": "Regular.ttf",
                "missing": "Missing.ttf",
                "broken": "Broken.ttf",
            },
        },
    )

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert set(config.fonts["literary"].faces) == {"regular"}
    assert "literary" in config.fonts
    assert "this face is excluded" in caplog.text


def test_invalid_regular_font_face_excludes_its_bundle(tmp_path: Path, caplog) -> None:
    package = tmp_path / "assets" / "fonts" / "unusable"
    (package / "Regular.ttf").parent.mkdir(parents=True)
    (package / "Regular.ttf").write_bytes(b"not a font")
    _write_manifest(
        package,
        "font.yaml",
        {"format": 1, "id": "unusable", "faces": {"regular": "Regular.ttf"}},
    )

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert "unusable" not in config.fonts
    assert "a usable regular face is required" in caplog.text


def test_all_duplicate_custom_identifiers_are_excluded_and_bundled_ids_are_reserved(tmp_path: Path, caplog) -> None:
    root = tmp_path / "assets" / "backgrounds"
    _write_png(root / "a" / "duplicate.png")
    _write_png(root / "b" / "duplicate.png")
    _write_png(root / "aged-paper.png")

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert "duplicate" not in config.backgrounds
    assert config.backgrounds["aged-paper"].bundled
    assert "share identifier 'duplicate'; all are excluded" in caplog.text
    assert "conflicts with reserved bundled identifier 'aged-paper'" in caplog.text


@pytest.mark.parametrize(
    ("identifier", "image", "expected_diagnostic"),
    [
        ("bad name", "image.png", "identifier"),
        ("escaped", "../outside.png", "within its asset package"),
        ("bad-separators", r"folder\image.png", "forward slashes"),
        ("future", "image.png", "manifest version 1"),
    ],
)
def test_invalid_background_manifests_are_isolated(
    tmp_path: Path, identifier: str, image: str, expected_diagnostic: str, caplog
) -> None:
    package = tmp_path / "assets" / "backgrounds" / "package"
    _write_png(package / "image.png")
    _write_manifest(
        package,
        "background.yaml",
        {"format": 2 if identifier == "future" else 1, "id": identifier, "image": image},
    )
    _write_png(tmp_path / "assets" / "backgrounds" / "good.png")

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert "good" in config.backgrounds
    assert identifier not in config.backgrounds
    assert expected_diagnostic in caplog.text


def test_manifest_symlink_cannot_escape_its_package(tmp_path: Path, caplog) -> None:
    outside = _write_png(tmp_path / "outside.png")
    package = tmp_path / "assets" / "backgrounds" / "linked"
    package.mkdir(parents=True)
    try:
        (package / "escape.png").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")
    _write_manifest(package, "background.yaml", {"format": 1, "id": "linked", "image": "escape.png"})

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert "linked" not in config.backgrounds
    assert "resolves outside its asset package" in caplog.text


def test_asset_symlinks_are_not_followed_during_discovery(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _write_png(outside / "linked.png")
    _write_manifest(outside / "package", "background.yaml", {"format": 1, "id": "linked-package", "image": "image.png"})
    _write_png(outside / "package" / "image.png")
    asset_root = tmp_path / "assets" / "backgrounds"
    asset_root.mkdir(parents=True)
    try:
        (asset_root / "linked.png").symlink_to(outside / "linked.png")
        (asset_root / "linked-package").symlink_to(outside / "package", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert "linked" not in config.backgrounds
    assert "linked-package" not in config.backgrounds


@pytest.mark.parametrize(
    "manifest",
    [
        {"format": 2, "id": "wrong-version", "faces": {"regular": "Regular.ttf"}},
        {"format": 1, "id": "no-regular", "faces": {"italic": "Regular.ttf"}},
        {"format": 1, "id": "bad-face", "faces": {"regular face": "Regular.ttf"}},
        {"format": 1, "id": "absolute-face", "faces": {"regular": "/tmp/Regular.ttf"}},
    ],
)
def test_invalid_font_bundles_are_excluded_independently(tmp_path: Path, manifest: dict[str, object], caplog) -> None:
    package = tmp_path / "assets" / "fonts" / str(manifest["id"])
    package.mkdir(parents=True)
    shutil.copyfile(_BUNDLED_LORA, package / "Regular.ttf")
    _write_manifest(package, "font.yaml", manifest)

    config = load_application_config(_write_config(tmp_path / "config.yaml"))

    assert manifest["id"] not in config.fonts
    assert "lora" in config.fonts
    assert str(manifest["id"]) in caplog.text


def test_legacy_available_mappings_are_ignored_with_migration_diagnostics(tmp_path: Path, caplog) -> None:
    data = _config_data(
        fonts={"default": ["lora"], "available": {"legacy": "font.ttf"}},
        backgrounds={"default": ["none"], "available": {"legacy": "paper.png"}},
        decorations={"default": ["none"], "available": {"legacy": {"image": "border.png"}}},
    )

    config = load_application_config(_write_config(tmp_path / "config.yaml", data))

    assert set(config.fonts) == {"alegreya", "libre-baskerville", "lora", "orbitron", "source-sans-3"}
    assert not ({"legacy"} & set(config.backgrounds))
    assert not ({"legacy"} & set(config.decorations))
    assert caplog.text.count("is no longer supported") == 3

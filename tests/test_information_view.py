from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import refrain.information_view as information_view
from refrain import load_application_config


def test_prepares_complete_application_owned_image_without_user_content(tmp_path: Path, monkeypatch) -> None:
    configuration = load_application_config(Path(__file__).parent.parent / "examples" / "config.yaml")
    configuration = replace(configuration, content_directory=tmp_path / "missing-content")
    compositions = []
    original_layout = information_view.layout_composition
    fitted_text = []
    direct_text = []
    original_draw_fitted = information_view._draw_fitted_text
    original_draw_text = ImageDraw.ImageDraw.text

    def capture_composition(composition, *args, **kwargs):
        compositions.append(composition)
        return original_layout(composition, *args, **kwargs)

    def capture_fitted_text(draw, text, font_data, bounds, **kwargs):
        result = original_draw_fitted(draw, text, font_data, bounds, **kwargs)
        fitted_text.append((text, bounds, result))
        return result

    def capture_direct_text(draw, position, text, *args, **kwargs):
        direct_text.append(text)
        return original_draw_text(draw, position, text, *args, **kwargs)

    monkeypatch.setattr(information_view, "layout_composition", capture_composition)
    monkeypatch.setattr(information_view, "_draw_fitted_text", capture_fitted_text)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_direct_text)

    image = information_view.prepare_information_view(configuration)
    try:
        assert image.mode == "RGB" and image.size == (1600, 1200)
        assert image.getpixel((0, 0)) == (250, 249, 245)
        with Image.new("RGB", image.size, image.getpixel((0, 0))) as blank:
            assert ImageChops.difference(image, blank).getbbox()
        assert len(compositions) == 1
        assert compositions[0].quotation == information_view._QUOTATION
        assert compositions[0].attribution == "Forge, Refrain Development Team"
        assert not configuration.content_directory.exists()
        assert any("Made for a quieter kind of noticing." in text for text, _, _ in fitted_text)
        assert any(text.startswith("Version 0.1.0") for text, _, _ in fitted_text)
        assert any("github.com/ControlForgeHQ/refrain" in text for text, _, _ in fitted_text)
        assert "ControlForge" in direct_text
        assert "© 2026 Edward Wright" in direct_text
        assert "1672" in direct_text
        assert any(bounds[1] >= 960 for _, bounds, _ in fitted_text)
    finally:
        image.close()


def test_omits_unavailable_optional_runtime_and_network_details(tmp_path: Path, monkeypatch) -> None:
    configuration = load_application_config(Path(__file__).parent.parent / "examples" / "config.yaml")
    configuration = replace(
        configuration,
        content_directory=tmp_path / "unavailable-library",
        display_backends=(),
    )
    monkeypatch.setattr(information_view, "_runtime_information", lambda: (None, None))
    monkeypatch.setattr(information_view, "_network_information", lambda _configuration: None)
    monkeypatch.setattr(information_view, "_application_version", lambda: "0.1.0")

    fitted_text = []
    original_draw_fitted = information_view._draw_fitted_text

    def capture_fitted_text(draw, text, font_data, bounds, **kwargs):
        fitted_text.append(text)
        return original_draw_fitted(draw, text, font_data, bounds, **kwargs)

    monkeypatch.setattr(information_view, "_draw_fitted_text", capture_fitted_text)
    image = information_view.prepare_information_view(configuration)
    try:
        assert image.size == (1600, 1200)
        assert not any("Linux" in text or "http" in text for text in fitted_text)
        assert "Version 0.1.0" in fitted_text
        assert not any("build" in text for text in fitted_text)
        paper = image.getpixel((0, 0))
        for bounds in ((92, 960, 622, 1120), (978, 960, 1508, 1120)):
            with (
                image.crop(bounds) as value_region,
                Image.new("RGB", (bounds[2] - bounds[0], bounds[3] - bounds[1]), paper) as blank,
            ):
                assert ImageChops.difference(value_region, blank).getbbox() is None
    finally:
        image.close()


def test_optional_build_metadata_requires_a_bounded_release_or_commit_identifier(monkeypatch) -> None:
    monkeypatch.setattr(information_view.platform, "system", lambda: "Linux")
    monkeypatch.setattr(information_view.platform, "machine", lambda: "x86_64")
    monkeypatch.setenv("REFRAIN_BUILD", "not-a-secret-token")
    monkeypatch.delenv("REFRAIN_COMMIT", raising=False)

    assert information_view._runtime_information()[1] is None

    monkeypatch.setenv("REFRAIN_BUILD", "v0.1.0")
    assert information_view._runtime_information()[1] == "v0.1.0"
    monkeypatch.setenv("REFRAIN_COMMIT", "abcdef0123456789")
    assert information_view._runtime_information()[1] == "abcdef012345"


def test_fitted_technical_text_wraps_long_network_values_without_overflow() -> None:
    font_data = information_view._read_font("source-sans-3").data
    image = Image.new("RGB", (560, 140), "white")
    try:
        fitted_size, lines = information_view._draw_fitted_text(
            ImageDraw.Draw(image),
            "https://" + "a" * 250 + ".example:8080/display/current",
            font_data,
            (10, 10, 530, 130),
            preferred_size=16,
            fill="#333333",
        )
        font = ImageFont.truetype(BytesIO(font_data), size=fitted_size)
        assert len(lines) > 1
        assert all(font.getlength(line) <= 520 for line in lines)
        assert len(lines) * (font.getbbox("Ag")[3] - font.getbbox("Ag")[1]) <= 120
        with Image.new("RGB", image.size, "white") as blank:
            difference = ImageChops.difference(image, blank)
        try:
            drawn_bounds = difference.getbbox()
        finally:
            difference.close()
        assert drawn_bounds is not None
        assert 10 <= drawn_bounds[0] <= drawn_bounds[2] <= 530
        assert 10 <= drawn_bounds[1] <= drawn_bounds[3] <= 130
    finally:
        image.close()


def test_preview_example_writes_complete_png_without_application_state(tmp_path: Path) -> None:
    repository = Path(__file__).parent.parent
    output = tmp_path / "information-view.png"
    result = subprocess.run(
        [
            sys.executable,
            str(repository / "examples" / "information_view.py"),
            "--config",
            str(repository / "examples" / "config.yaml"),
            "--output",
            str(output),
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 1200)

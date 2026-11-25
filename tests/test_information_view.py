from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

import refrain.information_view as information_view
from refrain import (
    ApplicationConfiguration,
    DisplayBackendConfiguration,
    DisplayOutputConfiguration,
    PresentationInsets,
    ResolvedOutputSpecification,
    RevealSchedule,
)


@pytest.fixture
def configuration(tmp_path: Path) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        file=tmp_path / "config.yaml",
        display_backends=(
            DisplayBackendConfiguration(
                "window",
                outputs=(
                    DisplayOutputConfiguration(
                        "window", ResolvedOutputSpecification("16:9", (1920, 1080)), audience="internal"
                    ),
                ),
            ),
        ),
        day_start=time(7),
        content_directory=tmp_path / "missing-content",
        reveal=RevealSchedule(time(13), time(19)),
        presentation_insets=PresentationInsets(384, 384, 324, 324),
        fonts={},
        default_fonts=(),
        min_font_size=28,
        max_font_size=100,
    )


def prepare_default_information_image(configuration):
    specification = configuration.required_output_specifications[0]
    return information_view.prepare_information_view(configuration, (specification,))[specification][0]


def test_prepares_complete_application_owned_image_without_user_content(configuration, monkeypatch) -> None:
    compositions = []
    fitted_text = []
    direct_text = []

    original_layout = information_view.layout_composition
    original_draw_fitted = information_view._draw_fitted_text
    original_draw_text = ImageDraw.ImageDraw.text

    def capture_composition(composition, *args, **kwargs):
        compositions.append(composition)
        return original_layout(composition, *args, **kwargs)

    def capture_fitted_text(draw, text, font_data, bounds, **kwargs):
        result = original_draw_fitted(draw, text, font_data, bounds, **kwargs)
        fitted_text.append(text)
        return result

    def capture_direct_text(draw, position, text, *args, **kwargs):
        direct_text.append(text)
        return original_draw_text(draw, position, text, *args, **kwargs)

    monkeypatch.setattr(information_view, "layout_composition", capture_composition)
    monkeypatch.setattr(information_view, "_draw_fitted_text", capture_fitted_text)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_direct_text)

    specification = ResolvedOutputSpecification("16:9", (1920, 1080))
    image = information_view.prepare_information_view(configuration, (specification,))[specification][0]
    try:
        assert image.mode == "RGB"
        assert image.size == specification.requested_output_size
        assert image.getpixel((0, 0)) == (250, 249, 245)

        with Image.new("RGB", image.size, image.getpixel((0, 0))) as blank:
            assert ImageChops.difference(image, blank).getbbox()

        assert len(compositions) == 1
        assert compositions[0].quotation == information_view._QUOTATION
        assert compositions[0].attribution == ("Forge, Refrain Development Team")

        assert not configuration.content_directory.exists()

        assert "Made for a quieter kind of noticing." in fitted_text
        assert any(text.startswith("Version ") for text in fitted_text)
        assert "github.com/ControlForgeHQ/refrain" in fitted_text
        assert "© 2026 Edward Wright" in fitted_text

        assert "RUNNING ON" in fitted_text
        assert "DISPLAY BACKENDS" in fitted_text
        assert "NETWORK" not in fitted_text

        assert "1672" in direct_text

        for filename in (
            "refrain-logo.png",
            "controlforge-logo.png",
        ):
            logo = information_view._read_logo(filename)
            assert logo is not None
            try:
                assert logo.mode == "RGBA"
                assert logo.getbbox() is not None
            finally:
                logo.close()

    finally:
        image.close()


@pytest.mark.parametrize(
    "missing_filename",
    [
        "controlforge-logo.png",
        "refrain-logo.png",
    ],
)
def test_missing_logo_does_not_prevent_information_view_rendering(
    configuration,
    monkeypatch,
    missing_filename: str,
) -> None:
    original_read_logo = information_view._read_logo

    def read_logo_with_missing_resource(filename: str):
        if filename == missing_filename:
            return None
        return original_read_logo(filename)

    monkeypatch.setattr(
        information_view,
        "_read_logo",
        read_logo_with_missing_resource,
    )

    image = prepare_default_information_image(configuration)
    try:
        assert image.mode == "RGB"
        assert image.size == configuration.required_output_specifications[0].requested_output_size
    finally:
        image.close()


def test_omits_unavailable_optional_runtime_details(configuration, monkeypatch) -> None:
    configuration = replace(
        configuration,
        display_backends=(),
    )

    monkeypatch.setattr(
        information_view,
        "_runtime_information",
        lambda: (None, None),
    )
    monkeypatch.setattr(
        information_view,
        "_application_version",
        lambda: "0.1.0",
    )

    fitted_text = []
    original_draw_fitted = information_view._draw_fitted_text

    def capture_fitted_text(draw, text, font_data, bounds, **kwargs):
        fitted_text.append(text)
        return original_draw_fitted(draw, text, font_data, bounds, **kwargs)

    monkeypatch.setattr(
        information_view,
        "_draw_fitted_text",
        capture_fitted_text,
    )

    specification = ResolvedOutputSpecification("16:9", (1920, 1080))
    image = information_view.prepare_information_view(configuration, (specification,))[specification][0]
    try:
        assert image.mode == "RGB"
        assert image.size == specification.requested_output_size

        assert "Version 0.1.0" in fitted_text
        assert not any("build" in text for text in fitted_text)

        assert "RUNNING ON" in fitted_text
        assert "DISPLAY BACKENDS" in fitted_text

        assert not any(
            "Python " in text or "Windows" in text or "Linux" in text or "PUBLISH" in text for text in fitted_text
        )

        assert "NETWORK" not in fitted_text
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
    font_data = ImageFont.load_default(size=20).font_bytes
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


def test_fitted_text_can_align_an_identity_block_to_its_right_edge() -> None:
    font_data = ImageFont.load_default(size=20).font_bytes
    image = Image.new("RGB", (520, 80), "white")
    try:
        information_view._draw_fitted_text(
            ImageDraw.Draw(image),
            "Short\nA considerably longer second line.",
            font_data,
            (10, 10, 500, 70),
            preferred_size=18,
            fill="#333333",
            right_align=True,
        )
        with Image.new("RGB", image.size, "white") as blank:
            difference = ImageChops.difference(image, blank)
        try:
            bounds = difference.getbbox()
        finally:
            difference.close()
        assert bounds is not None
        assert 10 <= bounds[0] < bounds[2] <= 500
        assert bounds[2] >= 496
    finally:
        image.close()


def test_preview_example_writes_complete_png_without_application_state(tmp_path: Path) -> None:
    repository = Path(__file__).parent.parent
    config = tmp_path / "config.yaml"
    config.write_text(
        'destinations:\n  - id: default\n    type: "window"\n    audience: "internal"\n'
        'fonts:\n  pools:\n    default: ["@builtin"]\n'
        'text:\n  colors:\n    pools:\n      default: ["@builtin"]\n',
        encoding="utf-8",
    )
    output = tmp_path / "information-view.png"
    result = subprocess.run(
        [
            sys.executable,
            str(repository / "examples" / "information_view.py"),
            "--config",
            str(config),
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
        assert image.size == (1920, 1080)


def test_information_view_prepares_the_requested_destination_variant(configuration) -> None:
    specification = ResolvedOutputSpecification("4:3", (1600, 1200))

    images = information_view.prepare_information_view(configuration, (specification,))
    image = images[specification][0]
    try:
        assert image.size == specification.requested_output_size
    finally:
        image.close()

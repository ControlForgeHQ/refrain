from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageChops

import refrain.information_view as information_view
from refrain import load_application_config


def test_prepares_complete_application_owned_image_without_user_content(tmp_path: Path, monkeypatch) -> None:
    configuration = load_application_config(Path(__file__).parent.parent / "examples" / "config.yaml")
    configuration = replace(configuration, content_directory=tmp_path / "missing-content")
    compositions = []
    original_layout = information_view.layout_composition

    def capture_composition(composition, *args, **kwargs):
        compositions.append(composition)
        return original_layout(composition, *args, **kwargs)

    monkeypatch.setattr(information_view, "layout_composition", capture_composition)

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

    image = information_view.prepare_information_view(configuration)
    try:
        assert image.size == (1600, 1200)
        paper = image.getpixel((0, 0))
        for bounds in ((140, 965, 580, 1010), (580, 965, 1020, 1010), (1020, 965, 1460, 1010)):
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

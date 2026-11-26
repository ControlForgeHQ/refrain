from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest
from PIL import ImageChops

import refrain.information_view as information_view
import refrain.preparation as preparation
from refrain.config import (
    ApplicationConfiguration,
    DestinationPresentation,
    FontResource,
    PreparedImageVariantKey,
    RevealSchedule,
)
from refrain.geometry import PresentationInsets, ResolvedOutputSpecification
from refrain.renderer import CompositionVisibility


@pytest.fixture
def configuration(tmp_path: Path) -> ApplicationConfiguration:
    font = Path(__file__).parent / "fixtures" / "fonts" / "Lora-Regular.ttf"
    return ApplicationConfiguration(
        file=tmp_path / "config.yaml",
        display_backends=(),
        day_start=time(6),
        content_directory=tmp_path / "content",
        reveal=RevealSchedule(time(12), time(18)),
        presentation_insets=PresentationInsets(384, 384, 216, 216),
        fonts={"lora": FontResource("lora", font, bundled=False)},
        default_fonts=("lora",),
        min_font_size=40,
        max_font_size=120,
        palette={"black": "#000000", "red": "#cc0000"},
    )


def test_fallback_uses_shared_fully_visible_literary_pipeline_without_state(configuration, tmp_path, monkeypatch):
    compositions = []
    visibility = []
    original_layout = preparation.layout_composition
    original_render = preparation.render_reveal_stages

    def capture_layout(composition, *args, **kwargs):
        compositions.append(composition)
        return original_layout(composition, *args, **kwargs)

    def capture_render(background, font, layout, stages, **kwargs):
        visibility.extend(stages)
        return original_render(background, font, layout, stages, **kwargs)

    monkeypatch.setattr(preparation, "layout_composition", capture_layout)
    monkeypatch.setattr(preparation, "render_reveal_stages", capture_render)
    monkeypatch.setattr(
        information_view, "_read_logo", lambda *_: pytest.fail("fallback must not use information-view branding")
    )
    existing = tmp_path / "state.json"
    existing.write_bytes(b"existing state")
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    images = information_view.prepare_no_eligible_fallback(configuration, (specification,))
    try:
        image = images[specification][0]
        assert image.mode == "RGB"
        assert image.size == (800, 500)
        assert len(images[specification]) == 1
        assert compositions[0].quotation == information_view._QUOTATION
        assert compositions[0].quotation == (
            "“The world is already full of remarkable things; we don't necessarily need to make them louder, "
            "bigger, or more complicated. Sometimes we just need to become better at noticing them.”"
        )
        assert compositions[0].attribution == "Forge, Refrain Development Team"
        assert compositions[0].source is None
        assert visibility == [CompositionVisibility(quotation=True, source=False, attribution=True)]
        assert existing.read_bytes() == b"existing state"
        assert sorted(path.name for path in tmp_path.iterdir()) == ["state.json"]
    finally:
        for stages in images.values():
            for image in stages:
                image.close()


def test_fallback_applies_destination_overrides_and_uses_one_canonical_choice(configuration, monkeypatch):
    specification = ResolvedOutputSpecification("16:10", (800, 500))
    red = PreparedImageVariantKey(specification, DestinationPresentation(text_color=("red",), font="lora"))
    calls = []
    original = preparation.resolve_canonical_presentation

    def capture_canonical(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(preparation, "resolve_canonical_presentation", capture_canonical)
    images = information_view.prepare_no_eligible_fallback(configuration, (specification, red))
    try:
        assert calls == [1]
        with ImageChops.difference(images[specification][0], images[red][0]) as difference:
            assert difference.getbbox() is not None
        assert images[red][0].size == specification.requested_output_size
    finally:
        for stages in images.values():
            for image in stages:
                image.close()


def test_fallback_rejects_empty_output_specifications(configuration):
    with pytest.raises(preparation.DailyImagePreparationError, match="output_specifications"):
        information_view.prepare_no_eligible_fallback(configuration, ())


def test_fallback_releases_prepared_images_after_later_output_failure(configuration, monkeypatch):
    images = []
    original = preparation._prepare_daily_images_for_specification

    def fail_second(*args, **kwargs):
        if images:
            raise preparation.DailyImagePreparationError("test failure")
        result = original(*args, **kwargs)
        images.extend(result)
        return result

    monkeypatch.setattr(preparation, "_prepare_daily_images_for_specification", fail_second)
    with pytest.raises(preparation.DailyImagePreparationError, match="test failure"):
        information_view.prepare_no_eligible_fallback(
            configuration,
            (ResolvedOutputSpecification("16:10", (800, 500)), ResolvedOutputSpecification("4:3", (800, 600))),
        )
    assert len(images) == 1
    with pytest.raises(ValueError, match="closed"):
        images[0].getpixel((0, 0))

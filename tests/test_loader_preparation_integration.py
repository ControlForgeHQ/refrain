from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pytest
import yaml
from PIL import Image
from resource_helpers import write_font_bundle

from refrain import (
    CompositionVisibility,
    DailySnapshot,
    SchedulingContext,
    build_eligible_quotation_pool,
    load_application_config,
    load_content_library,
    prepare_daily_images,
    resolve_reveal_stages,
    select_quotation,
)


@pytest.mark.parametrize(
    ("font_identifier", "settings", "stage_count"),
    [
        ("test-font", {}, 3),
        (
            "alternate-font",
            {"scheduling": {"day_start": "08:15", "reveal": {"source": "09:20", "attribution": "09:20"}}},
            2,
        ),
    ],
    ids=["omitted-optional-settings", "alternate-font-and-schedule"],
)
def test_loaded_configuration_and_content_prepare_self_contained_snapshot(
    tmp_path: Path, font_identifier: str, settings: dict[str, object], stage_count: int
) -> None:
    content_directory = tmp_path / "content"
    content_directory.mkdir()
    config_path = tmp_path / "config.yaml"
    write_font_bundle(tmp_path / "assets" / "fonts" / font_identifier, font_identifier)
    content_path = content_directory / "entry.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "storage": {"content": "content"},
                "destinations": [{"id": "window", "type": "window"}],
                "presentation": {"insets": {"left": 384, "right": 384, "top": 216, "bottom": 216}},
                "fonts": {"pools": {"default": [font_identifier]}},
                "text": {"min_font_size": 12, "max_font_size": 24},
                **settings,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    content_path.write_text(
        yaml.safe_dump(
            {
                "id": "integration-entry",
                "quotations": ["A quiet moment settles.", "A second thought remains."],
                "source": "A Sample Collection",
                "attribution": "An Example Author",
                "presentation_style": "left-aligned",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_application_config(config_path)
    entries = load_content_library(config.content_directory)
    pool = build_eligible_quotation_pool(entries, date(2026, 10, 26))
    proposal = select_quotation(pool, frozenset(), random.Random(0))
    candidate = proposal.selected_candidate
    assert candidate is not None
    entry = candidate.entry

    snapshot = DailySnapshot(
        entry_id=entry.id,
        quotation_text=candidate.text,
        quotation_identity=candidate.identity,
        source=entry.source,
        attribution=entry.attribution,
        presentation_style=entry.presentation_style,
        font=entry.font,
        font_faces=entry.font_faces,
        background=entry.background,
        decoration=entry.decoration,
        text_color=entry.text_color,
        decoration_color=entry.decoration_color,
        reveal_schedule={
            "quotation": config.day_start.strftime("%H:%M"),
            "source": config.reveal.source.strftime("%H:%M"),
            "attribution": config.reveal.attribution.strftime("%H:%M"),
        },
        scheduling=SchedulingContext(
            date(2026, 10, 26),
            config.day_start.strftime("%H:%M"),
        ),
    )
    assert snapshot.presentation_style == "left-aligned"

    config_path.unlink()
    content_path.unlink()
    stages = resolve_reveal_stages(snapshot)
    assert len(stages) == stage_count
    images = prepare_daily_images(snapshot, stages, config, config.required_output_specifications)

    assert not config_path.exists()
    assert not content_path.exists()
    assert len(images[config.required_output_specifications[0]]) == len(stages)
    images = images[config.required_output_specifications[0]]
    assert all(image.mode == "RGB" and image.size == (1920, 1080) for image in images)
    for image in images:
        image.close()


def test_category_registered_resources_load_through_rendering_pipeline(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    font_path = assets / "fonts" / "custom" / "Regular.ttf"
    background_path = assets / "backgrounds" / "paper" / "Paper.png"
    decoration_path = assets / "decorations" / "borders" / "Border.png"
    font_path.parent.mkdir(parents=True)
    background_path.parent.mkdir(parents=True)
    decoration_path.parent.mkdir(parents=True)
    write_font_bundle(font_path.parent, "family-serif")
    Image.new("RGB", (1600, 1200), (255, 0, 0)).save(background_path)
    decoration = Image.new("RGBA", (1600, 1200), (0, 0, 0, 0))
    decoration.paste((0, 0, 255, 255), (100, 50, 201, 151))
    decoration.save(decoration_path)
    (font_path.parent / "font.yaml").write_text(
        yaml.safe_dump(
            {"format": 1, "id": "family-serif", "faces": {"regular": "Regular.ttf"}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (background_path.parent / "background.yaml").write_text(
        yaml.safe_dump(
            {"format": 1, "id": "paper", "layers": [{"image": "Paper.png"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (decoration_path.parent / "decoration.yaml").write_text(
        yaml.safe_dump(
            {
                "format": 1,
                "id": "border",
                "tintable": False,
                "layers": [{"image": "Border.png", "method": "contain"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    content_directory = tmp_path / "content"
    content_directory.mkdir()
    (content_directory / "entry.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "category-resources",
                "font": "family-serif",
                "background": "paper",
                "decoration": "border",
                "quotations": ["A category-relative resource is rendered."],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "storage": {"content": "content"},
                "destinations": [{"id": "window", "type": "window"}],
                "presentation": {"insets": {"left": 384, "right": 384, "top": 216, "bottom": 216}},
                "fonts": {"pools": {"default": ["family-serif"]}},
                "backgrounds": {"pools": {"default": ["paper"]}},
                "decorations": {"pools": {"default": ["border"]}},
                "text": {"min_font_size": 28, "max_font_size": 36},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_application_config(config_path)
    entry = load_content_library(config.content_directory)[0]
    snapshot = DailySnapshot(
        entry_id=entry.id,
        quotation_text=entry.quotations[0].text,
        quotation_identity=entry.quotations[0].identity,
        source=entry.source,
        attribution=entry.attribution,
        presentation_style=entry.presentation_style,
        font=entry.font,
        font_faces=entry.font_faces,
        background=entry.background,
        decoration=entry.decoration,
        text_color=entry.text_color,
        decoration_color=entry.decoration_color,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 10, 26), "06:00"),
    )
    images = prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        config,
        config.required_output_specifications,
    )
    image = images[config.required_output_specifications[0]][0]

    assert config.fonts["family-serif"].path == font_path
    assert config.backgrounds["paper"].layers[0].image == background_path
    assert config.decorations["border"].layers[0].image == decoration_path
    assert image.size == (1920, 1080)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((375, 90)) == (0, 0, 255)
    image.close()

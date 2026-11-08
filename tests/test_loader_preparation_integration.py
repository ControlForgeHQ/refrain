from __future__ import annotations

import random
from datetime import date
from importlib.resources import files
from pathlib import Path

import yaml
from PIL import Image

from refrain import (
    CompositionVisibility,
    DailySnapshot,
    SchedulingContext,
    build_eligible_quotation_pool,
    load_application_config,
    load_content_library,
    prepare_daily_images,
    select_quotation,
)


def test_loaded_configuration_and_content_prepare_self_contained_snapshot(tmp_path: Path) -> None:
    content_directory = tmp_path / "content"
    content_directory.mkdir()
    config_path = tmp_path / "config.yaml"
    content_path = content_directory / "entry.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "general": {"day_start": "06:00"},
                "content": {"directory": "content"},
                "display": {"backends": [{"type": "window"}]},
                "layout": {
                    "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                    "fonts": {"default": ["lora"]},
                    "text": {"min_font_size": 12, "max_font_size": 24},
                },
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
    stages = (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )
    images = prepare_daily_images(snapshot, stages, config)

    assert not config_path.exists()
    assert not content_path.exists()
    assert len(images) == len(stages)
    assert all(image.mode == "RGB" and image.size == (1600, 1200) for image in images)


def test_category_registered_resources_load_through_rendering_pipeline(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    font_path = assets / "fonts" / "custom" / "Serif.ttf"
    background_path = assets / "backgrounds" / "paper" / "Paper.png"
    decoration_path = assets / "decorations" / "borders" / "Border.png"
    font_path.parent.mkdir(parents=True)
    background_path.parent.mkdir(parents=True)
    decoration_path.parent.mkdir(parents=True)
    font_path.write_bytes(files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf").read_bytes())
    Image.new("RGB", (1600, 1200), (255, 0, 0)).save(background_path)
    decoration = Image.new("RGBA", (1600, 1200), (0, 0, 0, 0))
    decoration.putpixel((1, 0), (0, 0, 255, 255))
    decoration.save(decoration_path)
    (font_path.parent / "font.yaml").write_text(
        yaml.safe_dump(
            {"format": 1, "id": "family-serif", "faces": {"regular": "Serif.ttf"}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (background_path.parent / "background.yaml").write_text(
        yaml.safe_dump({"format": 1, "id": "paper", "image": "Paper.png"}, sort_keys=False),
        encoding="utf-8",
    )
    (decoration_path.parent / "decoration.yaml").write_text(
        yaml.safe_dump({"format": 1, "id": "border", "image": "Border.png"}, sort_keys=False),
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
                "content": {"directory": "content"},
                "display": {"backends": [{"type": "window"}]},
                "layout": {
                    "presentation_region": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                    "fonts": {"default": ["family-serif"]},
                    "backgrounds": {"default": ["paper"]},
                    "decorations": {"default": ["border"]},
                    "text": {"min_font_size": 28, "max_font_size": 36},
                },
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
    image = prepare_daily_images(
        snapshot,
        (CompositionVisibility(),),
        config,
    )[0]

    assert config.fonts["family-serif"].path == font_path
    assert config.backgrounds["paper"].path == background_path
    assert config.decorations["border"].path == decoration_path
    assert image.size == (1600, 1200)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((1, 0)) == (0, 0, 255)
    image.close()

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import yaml

from refrain import (
    CompositionVisibility,
    DailySnapshot,
    ResolvedFont,
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
                "general": {"timezone": "Etc/UTC"},
                "content": {"directory": "content"},
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
                "presentation_style": "prose",
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

    font_resource = config.fonts["lora"]
    with font_resource.path.open("rb") as font_file:
        font = ResolvedFont(font_resource.identifier, font_file.read())
    snapshot = DailySnapshot(
        quotation_text=candidate.text,
        quotation_identity=candidate.identity,
        font=font,
        presentation_metadata={
            "source": entry.source,
            "attribution": entry.attribution,
            "presentation_style": entry.presentation_style,
        },
        reveal_schedule={
            "quotation": config.reveal.quotation.strftime("%H:%M"),
            "source": config.reveal.source.strftime("%H:%M"),
            "attribution": config.reveal.attribution.strftime("%H:%M"),
        },
        layout={
            "image_size": (320, 240),
            "presentation_region": {
                "x": config.presentation_region.x,
                "y": config.presentation_region.y,
                "width": config.presentation_region.width,
                "height": config.presentation_region.height,
            },
            "min_font_size": config.min_font_size,
            "max_font_size": config.max_font_size,
        },
        scheduling=SchedulingContext(
            date(2026, 10, 26),
            config.timezone.key,
            config.day_start.strftime("%H:%M"),
        ),
    )

    config_path.unlink()
    content_path.unlink()
    stages = (
        CompositionVisibility(),
        CompositionVisibility(source=True),
        CompositionVisibility(source=True, attribution=True),
    )
    images = prepare_daily_images(snapshot, stages)

    assert not config_path.exists()
    assert not content_path.exists()
    assert len(images) == len(stages)
    assert all(image.mode == "RGB" and image.size == (320, 240) for image in images)

"""Generate daily reveal images from representative committed snapshot data."""

from __future__ import annotations

import argparse
from datetime import date
from importlib.resources import files
from pathlib import Path

from refrain import (
    CompositionVisibility,
    DailySnapshot,
    FontResource,
    SchedulingContext,
    prepare_daily_images,
)

_QUOTATION = (
    "A patient observer notices the changing light, the softened edges of the room, "
    "and the small details that attention brings into view."
)
_STAGES = (
    CompositionVisibility(),
    CompositionVisibility(source=True),
    CompositionVisibility(source=True, attribution=True),
)
_FONT_REGISTRY = {
    "lora": FontResource(
        "lora",
        files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf"),
        bundled=True,
    )
}


def _example_snapshot() -> DailySnapshot:
    return DailySnapshot(
        quotation_text=_QUOTATION,
        quotation_identity=_QUOTATION,
        font_identifier="lora",
        presentation_metadata={
            "source": "Notes on Patient Looking",
            "attribution": "An Example Author",
            "presentation_style": "centered",
        },
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        layout={
            "image_size": (1600, 1200),
            "presentation_region": {"x": 0.1, "y": 0.225, "width": 0.8, "height": 0.55},
            "min_font_size": 28,
            "max_font_size": 100,
        },
        scheduling=SchedulingContext(date(2026, 10, 26), "Etc/UTC", "06:00"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path, help="directory in which daily-stage PNG files are saved")
    output_directory = parser.parse_args().output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    images = prepare_daily_images(_example_snapshot(), _STAGES, _FONT_REGISTRY)
    for index, image in enumerate(images):
        path = output_directory / f"daily-reveal-stage-{index}.png"
        image.save(path)
        print(path)


if __name__ == "__main__":
    main()

"""Generate daily reveal images from representative committed snapshot data."""

from __future__ import annotations

import argparse
from datetime import date, time
from importlib.resources import files
from pathlib import Path

from refrain import (
    ApplicationConfiguration,
    CompositionVisibility,
    DailySnapshot,
    DisplayBackendConfiguration,
    FontResource,
    PresentationInsets,
    RevealSchedule,
    SchedulingContext,
    normalize_quotation,
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
        entry_id="example",
        quotation_text=_QUOTATION,
        quotation_identity=normalize_quotation(_QUOTATION),
        source="Notes on Patient Looking",
        attribution="An Example Author",
        presentation_style="centered",
        font="lora",
        font_faces={},
        background=None,
        decoration=None,
        text_color=None,
        decoration_color=None,
        reveal_schedule={"quotation": "06:00", "source": "12:00", "attribution": "18:00"},
        scheduling=SchedulingContext(date(2026, 10, 26), "Etc/UTC", "06:00"),
    )


def _example_configuration() -> ApplicationConfiguration:
    return ApplicationConfiguration(
        file=Path.cwd() / "example-config.yaml",
        display_backends=(DisplayBackendConfiguration("window"),),
        day_start=time(6),
        content_directory=Path.cwd() / "content",
        reveal=RevealSchedule(time(12), time(18)),
        output_size=(1920, 1080),
        presentation_insets=PresentationInsets(384, 384, 324, 324),
        fonts=_FONT_REGISTRY,
        default_fonts=("lora",),
        min_font_size=28,
        max_font_size=100,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path, help="directory in which daily-stage PNG files are saved")
    output_directory = parser.parse_args().output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    images = prepare_daily_images(_example_snapshot(), _STAGES, _example_configuration())
    try:
        for index, image in enumerate(images):
            path = output_directory / f"daily-reveal-stage-{index}.png"
            image.save(path)
            print(path)
    finally:
        for image in images:
            image.close()


if __name__ == "__main__":
    main()

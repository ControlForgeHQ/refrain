"""Generate hardware-independent literary composition previews."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

from PIL import Image

from refrain import (
    CompositionVisibility,
    LiteraryComposition,
    QuotationRegion,
    ResolvedFont,
    layout_composition,
    render_reveal_stages,
)

_COMPOSITIONS = {
    "both-fields": (
        LiteraryComposition(
            quotation=(
                "A patient observer notices the changing light, the softened edges of the room, "
                "and the small details that attention brings into view."
            ),
            source="Notes on Patient Looking",
            attribution="An Example Author",
        ),
        (
            CompositionVisibility(),
            CompositionVisibility(source=True),
            CompositionVisibility(source=True, attribution=True),
        ),
    ),
    "source-only": (
        LiteraryComposition(
            quotation="Begin with a little quiet, and let the thought arrive in its own time.",
            source="A Book of Patient Reading",
        ),
        (CompositionVisibility(), CompositionVisibility(source=True)),
    ),
    "attribution-only": (
        LiteraryComposition(
            quotation="The ordinary world has room for another careful look.",
            attribution="An Example Author",
        ),
        (CompositionVisibility(), CompositionVisibility(attribution=True)),
    ),
    "neither": (
        LiteraryComposition(quotation="Be still."),
        (CompositionVisibility(),),
    ),
}
_STYLES = ("centered", "prose")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path, help="directory in which preview PNG files are saved")
    output_directory = parser.parse_args().output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    font_resource = files("refrain").joinpath("assets", "fonts", "libre-baskerville", "LibreBaskerville-Regular.ttf")
    with font_resource.open("rb") as font_file:
        font = ResolvedFont("libre-baskerville", font_file.read())

    region = QuotationRegion(x=0.1, y=0.15, width=0.8, height=0.55)
    for composition_name, (composition, stages) in _COMPOSITIONS.items():
        for style in _STYLES:
            background = Image.new("RGB", (1600, 1200), "#f8f6f0")
            layout = layout_composition(
                composition,
                font,
                region,
                background.size,
                min_font_size=32,
                max_font_size=104,
                presentation_style=style,
            )
            images = render_reveal_stages(background, font, layout, stages)
            for stage_index, image in enumerate(images):
                path = output_directory / f"{composition_name}-{style}-reveal-stage-{stage_index}.png"
                image.save(path)
                print(f"{path}: {layout.quotation.font_size}px, {len(layout.quotation.lines)} lines")


if __name__ == "__main__":
    main()

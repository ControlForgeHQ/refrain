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
    "short": LiteraryComposition(
        quotation="Be still.",
        source="Notes on Attention",
        attribution="An Example Author",
    ),
    "long": LiteraryComposition(
        quotation=(
            "A patient observer notices the changing light, the softened edges of the room, "
            "and the small details that become visible only when attention has time to settle. "
            "Each careful pause gives the ordinary world another chance to become unfamiliar."
        ),
        source="A Study of Looking Carefully",
        attribution="An Example Author",
    ),
    "paragraphs": LiteraryComposition(
        quotation=(
            "Begin with a little quiet.\nLet the thought arrive in its own time.\n\n"
            "Then leave room for what follows."
        ),
        source="A Book of Patient Reading",
        attribution="An Example Author",
    ),
}
_STAGES = (
    CompositionVisibility(),
    CompositionVisibility(source=True),
    CompositionVisibility(source=True, attribution=True),
)
_STYLES = ("centered", "prose")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path, help="directory in which preview PNG files are saved")
    output_directory = parser.parse_args().output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    font_resource = files("refrain").joinpath("assets", "fonts", "libre-baskerville", "LibreBaskerville-Regular.ttf")
    with font_resource.open("rb") as font_file:
        font = ResolvedFont("libre-baskerville", font_file.read())

    region = QuotationRegion(x=0.12, y=0.1, width=0.76, height=0.8)
    for composition_name, composition in _COMPOSITIONS.items():
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
            images = render_reveal_stages(background, font, layout, _STAGES)
            for stage_index, image in enumerate(images):
                path = output_directory / f"{composition_name}-{style}-stage-{stage_index}.png"
                image.save(path)
                print(f"{path}: {layout.quotation.font_size}px, {len(layout.quotation.lines)} lines")


if __name__ == "__main__":
    main()

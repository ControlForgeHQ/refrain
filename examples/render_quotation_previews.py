"""Generate hardware-independent literary composition previews."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

from PIL import Image

from refrain import (
    CompositionVisibility,
    LiteraryComposition,
    PresentationInsets,
    ResolvedFont,
    layout_composition,
    render_reveal_stages,
    resolve_presentation_geometry,
)

_OUTPUT_SIZE = (1920, 1080)
_LITERARY_BOUNDS = resolve_presentation_geometry(
    _OUTPUT_SIZE,
    PresentationInsets(left=384, right=384, top=324, bottom=324),
).output_region
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
_STYLES = ("centered", "left-aligned")
_FONTS = {
    "libre-baskerville": "LibreBaskerville-Regular.ttf",
    "lora": "Lora-Regular.ttf",
    "source-sans-3": "SourceSans3-Regular.ttf",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path, help="directory in which preview PNG files are saved")
    output_directory = parser.parse_args().output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    for font_identifier, filename in _FONTS.items():
        font_resource = files("refrain").joinpath("assets", "fonts", font_identifier, filename)
        with font_resource.open("rb") as font_file:
            font = ResolvedFont(font_identifier, font_file.read())
        font_directory = output_directory / font_identifier
        font_directory.mkdir(parents=True, exist_ok=True)

        for composition_name, (composition, stages) in _COMPOSITIONS.items():
            for style in _STYLES:
                background = Image.new("RGB", _OUTPUT_SIZE, "#FFFFFF")
                layout = layout_composition(
                    composition,
                    font,
                    _LITERARY_BOUNDS,
                    background.size,
                    min_font_size=32,
                    max_font_size=104,
                    presentation_style=style,
                    byline_gap_factor=1.20,
                )
                has_concealed_fields = composition.source is not None or composition.attribution is not None
                if not has_concealed_fields:
                    images = render_reveal_stages(background, font, layout, stages)
                    path = font_directory / f"{composition_name}-{style}-quotation-only.png"
                    images[0].save(path)
                    print(f"{path}: {layout.quotation.font_size}px, {len(layout.quotation.lines)} lines")
                    continue

                images = render_reveal_stages(background, font, layout, stages)
                for stage_index, (stage, image) in enumerate(zip(stages, images, strict=True)):
                    path = font_directory / f"{composition_name}-{style}-reveal-stage-{stage_index}.png"
                    image.save(path)
                    print(f"{path}: {layout.quotation.font_size}px, {len(layout.quotation.lines)} lines")


if __name__ == "__main__":
    main()

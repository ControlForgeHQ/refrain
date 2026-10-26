"""Generate hardware-independent quotation renderer previews."""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

from PIL import Image

from refrain import QuotationRegion, ResolvedFont, layout_quotation, render_quotation

_QUOTATIONS = {
    "short": "Be still.",
    "long": (
        "A patient observer notices the changing light, the softened edges of the room, "
        "and the small details that become visible only when attention has time to settle. "
        "Each careful pause gives the ordinary world another chance to become unfamiliar."
    ),
    "paragraphs": (
        "Begin with a little quiet.\nLet the thought arrive in its own time.\n\n" "Then leave room for what follows."
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path, help="directory in which preview PNG files are saved")
    output_directory = parser.parse_args().output_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    font_resource = files("refrain").joinpath("assets", "fonts", "libre-baskerville", "LibreBaskerville-Regular.ttf")
    with font_resource.open("rb") as font_file:
        font = ResolvedFont("libre-baskerville", font_file.read())

    region = QuotationRegion(x=0.12, y=0.1, width=0.76, height=0.8)
    for name, text in _QUOTATIONS.items():
        background = Image.new("RGB", (1600, 1200), "#f8f6f0")
        layout = layout_quotation(text, font, region, background.size, min_font_size=32, max_font_size=104)
        render_quotation(background, font, layout).save(output_directory / f"{name}.png")
        print(f"{output_directory / f'{name}.png'}: {layout.font_size}px, {len(layout.lines)} lines")


if __name__ == "__main__":
    main()

"""Display and replace two PNG images in one responsive desktop window."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from refrain.display import create_display_backend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_image", type=Path, help="PNG image to display first")
    parser.add_argument("second_image", type=Path, help="PNG image to display in the same window")
    arguments = parser.parse_args()

    display = create_display_backend("window")
    try:
        with Image.open(arguments.first_image) as image:
            display.update(image)
        input("The window remains responsive. Press Enter to replace the image...")
        with Image.open(arguments.second_image) as image:
            display.update(image)
        input("Press Enter to close the display...")
    finally:
        display.close()


if __name__ == "__main__":
    main()

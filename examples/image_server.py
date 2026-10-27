"""Serve and replace two PNG images through the image-server backend."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from refrain.display import create_display_backend


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_image", type=Path, help="PNG image to serve first")
    parser.add_argument("second_image", type=Path, help="PNG image to serve after the first")
    parser.add_argument("--host", default="127.0.0.1", help="local bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="TCP port (default: 8080)")
    arguments = parser.parse_args()

    display = create_display_backend(
        "image-server",
        image_server_host=arguments.host,
        image_server_port=arguments.port,
    )
    try:
        with Image.open(arguments.first_image) as image:
            display.update(image)
        browser_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(arguments.host, arguments.host)
        if ":" in browser_host:
            browser_host = f"[{browser_host}]"
        print(f"Serving the current PNG at http://{browser_host}:{arguments.port}/display/current")
        input("Press Enter to replace it with the second image...")
        with Image.open(arguments.second_image) as image:
            display.update(image)
        input("Press Enter to stop the image server...")
    finally:
        display.close()


if __name__ == "__main__":
    main()

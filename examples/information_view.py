"""Render Refrain's startup information view to a standalone PNG."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from refrain.config import load_application_config
from refrain.geometry import ResolvedOutputSpecification
from refrain.information_view import prepare_information_view


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="application YAML configuration")
    parser.add_argument("--output", type=Path, required=True, help="output PNG path")
    arguments = parser.parse_args(argv)

    configuration = load_application_config(arguments.config)
    specification = ResolvedOutputSpecification("16:9", (1920, 1080))
    image = prepare_information_view(configuration, (specification,))[specification][0]
    try:
        image.save(arguments.output, format="PNG")
    finally:
        image.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

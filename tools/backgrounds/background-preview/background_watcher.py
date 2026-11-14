from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

RGB_DIR = SCRIPT_DIR / "rgb"
SPECTRA6_DIR = SCRIPT_DIR / "spectra6"

STAGING_DIR = SCRIPT_DIR / "assets" / "backgrounds"
STAGING_PATH = STAGING_DIR / "preview-temp.png"

POLL_INTERVAL_SECONDS = 0.5
STABILITY_SECONDS = 1.0


def is_source_png(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".png"


def preview_paths(source: Path) -> tuple[Path, Path]:
    return (
        RGB_DIR / f"{source.stem}-rgb.png",
        SPECTRA6_DIR / f"{source.stem}-spectra6.png",
    )


def run_viewer(arguments: list[str]) -> None:
    print("$ " + subprocess.list2cmdline(arguments))
    subprocess.run(arguments, cwd=SCRIPT_DIR, check=True)


def generate_previews(source: Path) -> None:
    rgb_output, spectra6_output = preview_paths(source)

    print(f"\nProcessing {source.name}")

    # Preview files are disposable. Remove stale versions before generating
    # their replacements.
    rgb_output.unlink(missing_ok=True)
    spectra6_output.unlink(missing_ok=True)

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    RGB_DIR.mkdir(parents=True, exist_ok=True)
    SPECTRA6_DIR.mkdir(parents=True, exist_ok=True)

    # Refrain discovers standalone backgrounds by filename stem, so stage the
    # candidate under one known valid resource identifier.
    shutil.copy2(source, STAGING_PATH)

    try:
        run_viewer(
            [
                "refrain-viewer",
                "--config",
                str(CONFIG_PATH),
                "--background",
                "preview-temp",
                "--decoration",
                "none",
                "--text-color",
                "black",
                "--no-qr",
                "--aspect",
                "16:10",
                "--resolution",
                "3840",
                "2400",
                "--output",
                str(rgb_output),
            ]
        )

        run_viewer(
            [
                "refrain-viewer",
                "--config",
                str(CONFIG_PATH),
                "--background",
                "preview-temp",
                "--decoration",
                "none",
                "--text-color",
                "black",
                "--no-qr",
                "--render-as",
                "waveshare-13in3-e",
                "--output",
                str(spectra6_output),
            ]
        )

    finally:
        STAGING_PATH.unlink(missing_ok=True)

    print(f"Created {rgb_output.relative_to(SCRIPT_DIR)}")
    print(f"Created {spectra6_output.relative_to(SCRIPT_DIR)}")


def snapshot_sources() -> dict[Path, tuple[int, int]]:
    snapshot: dict[Path, tuple[int, int]] = {}

    # Only inspect PNG files directly beside this script. Generated previews
    # live in subdirectories and are therefore never considered source files.
    for path in SCRIPT_DIR.iterdir():
        if not is_source_png(path):
            continue

        stat = path.stat()
        snapshot[path] = (stat.st_size, stat.st_mtime_ns)

    return snapshot


def delete_previews(source: Path) -> None:
    rgb_output, spectra6_output = preview_paths(source)

    removed = False

    if rgb_output.exists():
        rgb_output.unlink()
        removed = True

    if spectra6_output.exists():
        spectra6_output.unlink()
        removed = True

    if removed:
        print(f"Removed previews for {source.name}")


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"Missing configuration: {CONFIG_PATH}")
        return 1

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    RGB_DIR.mkdir(parents=True, exist_ok=True)
    SPECTRA6_DIR.mkdir(parents=True, exist_ok=True)

    # path -> (last observed file state, time that state first appeared)
    observed: dict[Path, tuple[tuple[int, int], float]] = {}

    # path -> file state that was most recently rendered successfully
    processed: dict[Path, tuple[int, int]] = {}

    print(f"Watching: {SCRIPT_DIR}")
    print("Drop or replace PNG files beside this script to generate previews.")
    print(f"RGB previews:      {RGB_DIR}")
    print(f"Spectra-6 previews: {SPECTRA6_DIR}")
    print("Press Ctrl-C to stop.\n")

    try:
        while True:
            now = time.monotonic()
            current = snapshot_sources()

            # Detect source files that have been removed and clean up their
            # corresponding generated previews.
            known_paths = set(observed) | set(processed)

            for path in known_paths:
                if path in current:
                    continue

                observed.pop(path, None)
                processed.pop(path, None)
                delete_previews(path)

            for path, state in current.items():
                previous = observed.get(path)

                if previous is None or previous[0] != state:
                    # New file or file still being copied/modified. Restart the
                    # stability timer rather than attempting to read it early.
                    observed[path] = (state, now)
                    continue

                stable_since = previous[1]

                if now - stable_since < STABILITY_SECONDS:
                    continue

                if processed.get(path) == state:
                    continue

                try:
                    generate_previews(path)

                except subprocess.CalledProcessError as error:
                    print(
                        f"Preview generation failed for {path.name} "
                        f"with exit code {error.returncode}"
                    )

                except Exception as error:
                    print(f"Preview generation failed for {path.name}: {error}")

                else:
                    processed[path] = state

            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
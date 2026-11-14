from __future__ import annotations

import os
import re
import runpy
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SCRIPT_DIR = Path(__file__).resolve().parent

CONFIG_PATH = SCRIPT_DIR / "config.yaml"
SECRETS_PATH = SCRIPT_DIR / "background_secrets.py"

RGB_DIR = SCRIPT_DIR / "rgb"
SPECTRA6_DIR = SCRIPT_DIR / "spectra6"
PUSH_DIR = SCRIPT_DIR / "push"

STAGING_DIR = SCRIPT_DIR / "assets" / "backgrounds"
STAGING_PATH = STAGING_DIR / "preview-temp.png"

POLL_INTERVAL_SECONDS = 0.5
STABILITY_SECONDS = 1.0

RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

SECRETS_TEMPLATE = '''\
# Local-only settings for tools/backgrounds/watch_backgrounds.py.
#
# This file contains machine-specific connection settings and must not be
# committed to Git.

PI_HOST = "refrain"
PI_USER = "admin"

# Leave empty to use the normal SSH agent/config/default-key lookup.
# "~" and environment variables are expanded locally.
PI_IDENTITY_FILE = "~/.ssh/id_rsa"

# Paths below are relative to the remote user's home directory.
PI_REMOTE_BACKGROUND_DIR = ".config/refrain/assets/backgrounds"
PI_VENV_PATH = "refrain/.venv"

# Refrain runtime destination to receive the transient preview.
PI_DESTINATION = "waveshare-13in3-e"
'''


@dataclass(frozen=True)
class PushConfig:
    host: str
    user: str
    identity_file: Path | None
    remote_background_dir: str
    venv_path: str
    destination: str


def is_png(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".png"


def file_state(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def snapshot_pngs(directory: Path) -> dict[Path, tuple[int, int]]:
    snapshot: dict[Path, tuple[int, int]] = {}

    if not directory.exists():
        return snapshot

    for path in directory.iterdir():
        if is_png(path):
            snapshot[path] = file_state(path)

    return snapshot


def preview_paths(source: Path) -> tuple[Path, Path]:
    return (
        RGB_DIR / f"{source.stem}-rgb.png",
        SPECTRA6_DIR / f"{source.stem}-spectra6.png",
    )


def run_command(arguments: list[str], *, cwd: Path | None = None) -> None:
    print("$ " + subprocess.list2cmdline(arguments))
    subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
    )


def generate_previews(source: Path) -> None:
    rgb_output, spectra6_output = preview_paths(source)

    print(f"\nProcessing {source.name}")

    rgb_output.unlink(missing_ok=True)
    spectra6_output.unlink(missing_ok=True)

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    RGB_DIR.mkdir(parents=True, exist_ok=True)
    SPECTRA6_DIR.mkdir(parents=True, exist_ok=True)

    # Refrain discovers standalone backgrounds by filename stem, so stage the
    # current candidate under one known valid resource identifier.
    shutil.copy2(source, STAGING_PATH)

    try:
        run_command(
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
            ],
            cwd=SCRIPT_DIR,
        )

        run_command(
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
            ],
            cwd=SCRIPT_DIR,
        )

    finally:
        STAGING_PATH.unlink(missing_ok=True)

    print(f"Created {rgb_output.relative_to(SCRIPT_DIR)}")
    print(f"Created {spectra6_output.relative_to(SCRIPT_DIR)}")


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


def ensure_secrets_file() -> None:
    if SECRETS_PATH.exists():
        return

    SECRETS_PATH.write_text(SECRETS_TEMPLATE, encoding="utf-8")

    print(f"Created {SECRETS_PATH.name}")
    print("Edit it if the Pi connection settings need to be changed.\n")


def expand_local_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def validate_remote_relative_path(name: str, value: str) -> str:
    path = PurePosixPath(value)

    if path.is_absolute():
        raise ValueError(
            f"{name} must be relative to the remote user's home directory"
        )

    if not path.parts:
        raise ValueError(f"{name} must not be empty")

    if ".." in path.parts:
        raise ValueError(f"{name} must not contain '..'")

    return path.as_posix()


def load_push_config() -> PushConfig:
    values = runpy.run_path(str(SECRETS_PATH))

    host = str(values.get("PI_HOST", "")).strip()
    user = str(values.get("PI_USER", "")).strip()
    identity_value = str(values.get("PI_IDENTITY_FILE", "")).strip()

    remote_background_dir = str(
        values.get(
            "PI_REMOTE_BACKGROUND_DIR",
            ".config/refrain/assets/backgrounds",
        )
    ).strip()

    venv_path = str(
        values.get(
            "PI_VENV_PATH",
            "refrain/.venv",
        )
    ).strip()

    destination = str(
        values.get(
            "PI_DESTINATION",
            "waveshare-13in3-e",
        )
    ).strip()

    if not host:
        raise ValueError("PI_HOST is not configured")

    if not user:
        raise ValueError("PI_USER is not configured")

    if not destination:
        raise ValueError("PI_DESTINATION is not configured")

    remote_background_dir = validate_remote_relative_path(
        "PI_REMOTE_BACKGROUND_DIR",
        remote_background_dir,
    )

    venv_path = validate_remote_relative_path(
        "PI_VENV_PATH",
        venv_path,
    )

    identity_file: Path | None = None

    if identity_value:
        identity_file = expand_local_path(identity_value)

        if not identity_file.is_file():
            raise ValueError(
                f"PI_IDENTITY_FILE does not exist: {identity_file}"
            )

    return PushConfig(
        host=host,
        user=user,
        identity_file=identity_file,
        remote_background_dir=remote_background_dir,
        venv_path=venv_path,
        destination=destination,
    )


def ssh_base_arguments(config: PushConfig) -> list[str]:
    arguments = ["ssh"]

    if config.identity_file is not None:
        arguments.extend(["-i", str(config.identity_file)])

    arguments.append(f"{config.user}@{config.host}")

    return arguments


def scp_base_arguments(config: PushConfig) -> list[str]:
    arguments = ["scp"]

    if config.identity_file is not None:
        arguments.extend(["-i", str(config.identity_file)])

    return arguments


def push_background(source: Path) -> None:
    background_id = source.stem

    if not RESOURCE_ID_PATTERN.fullmatch(background_id):
        raise ValueError(
            f"{source.name} cannot be pushed because {background_id!r} "
            "is not a valid Refrain resource ID"
        )

    config = load_push_config()

    remote_target = f"{config.user}@{config.host}"
    remote_file = (
        f"{remote_target}:"
        f"{config.remote_background_dir}/{source.name}"
    )

    print(f"\nPushing {source.name} to {remote_target}")

    # Ensure the remote background directory exists.
    remote_directory_command = (
        "mkdir -p "
        f"$HOME/{shlex.quote(config.remote_background_dir)}"
    )

    run_command(
        [
            *ssh_base_arguments(config),
            remote_directory_command,
        ]
    )

    # SCP overwrites an existing file with the same name.
    run_command(
        [
            *scp_base_arguments(config),
            str(source),
            remote_file,
        ]
    )

    viewer_arguments = shlex.join(
        [
            "refrain-viewer",
            "--background",
            background_id,
            "--decoration",
            "none",
            "--no-qr",
            "--push",
            config.destination,
        ]
    )

    # Activate the configured remote Refrain virtual environment before
    # invoking refrain-viewer.
    viewer_command = (
        f". $HOME/{shlex.quote(config.venv_path)}/bin/activate && "
        f"{viewer_arguments}"
    )

    run_command(
        [
            *ssh_base_arguments(config),
            viewer_command,
        ]
    )

    print(
        f"Pushed {background_id!r} to Refrain destination "
        f"{config.destination!r}"
    )


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"Missing configuration: {CONFIG_PATH}")
        return 1

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    RGB_DIR.mkdir(parents=True, exist_ok=True)
    SPECTRA6_DIR.mkdir(parents=True, exist_ok=True)
    PUSH_DIR.mkdir(parents=True, exist_ok=True)

    ensure_secrets_file()

    # ------------------------------------------------------------------
    # Local preview watcher
    #
    # Existing PNGs beside the script are intentionally processed after
    # startup.
    # ------------------------------------------------------------------

    preview_observed: dict[
        Path,
        tuple[tuple[int, int], float],
    ] = {}

    preview_processed: dict[
        Path,
        tuple[int, int],
    ] = {}

    # ------------------------------------------------------------------
    # Remote push watcher
    #
    # Existing files in push/ are deliberately baselined as already
    # handled. Only files added or changed after startup cause a remote
    # upload and physical-display update.
    # ------------------------------------------------------------------

    initial_push_files = snapshot_pngs(PUSH_DIR)

    push_observed: dict[
        Path,
        tuple[tuple[int, int], float],
    ] = {
        path: (state, time.monotonic())
        for path, state in initial_push_files.items()
    }

    push_attempted: dict[
        Path,
        tuple[int, int],
    ] = dict(initial_push_files)

    print(f"Watching: {SCRIPT_DIR}")
    print("Drop or replace PNG files beside this script to generate previews.")
    print(f"RGB previews:        {RGB_DIR}")
    print(f"Spectra-6 previews:  {SPECTRA6_DIR}")
    print()
    print(f"Remote push folder:  {PUSH_DIR}")
    print("New or modified PNGs in push/ will be uploaded and displayed.")
    print("Existing push/ files are ignored at startup.")
    print()
    print("Press Ctrl-C to stop.\n")

    try:
        while True:
            now = time.monotonic()

            # ==========================================================
            # Local RGB / Spectra-6 preview watcher
            # ==========================================================

            preview_current = snapshot_pngs(SCRIPT_DIR)

            known_preview_paths = (
                set(preview_observed)
                | set(preview_processed)
            )

            for path in known_preview_paths:
                if path in preview_current:
                    continue

                preview_observed.pop(path, None)
                preview_processed.pop(path, None)
                delete_previews(path)

            for path, state in preview_current.items():
                previous = preview_observed.get(path)

                if previous is None or previous[0] != state:
                    preview_observed[path] = (state, now)
                    continue

                stable_since = previous[1]

                if now - stable_since < STABILITY_SECONDS:
                    continue

                if preview_processed.get(path) == state:
                    continue

                try:
                    generate_previews(path)

                except subprocess.CalledProcessError as error:
                    print(
                        f"Preview generation failed for {path.name} "
                        f"with exit code {error.returncode}"
                    )

                except Exception as error:
                    print(
                        f"Preview generation failed for "
                        f"{path.name}: {error}"
                    )

                else:
                    preview_processed[path] = state

            # ==========================================================
            # Remote push watcher
            # ==========================================================

            push_current = snapshot_pngs(PUSH_DIR)

            known_push_paths = (
                set(push_observed)
                | set(push_attempted)
            )

            for path in known_push_paths:
                if path in push_current:
                    continue

                push_observed.pop(path, None)
                push_attempted.pop(path, None)

            for path, state in push_current.items():
                previous = push_observed.get(path)

                if previous is None or previous[0] != state:
                    # New or changed file. Start/restart its stability timer
                    # before attempting network operations.
                    push_observed[path] = (state, now)
                    continue

                stable_since = previous[1]

                if now - stable_since < STABILITY_SECONDS:
                    continue

                if push_attempted.get(path) == state:
                    continue

                # Record this exact file state as attempted before external
                # side effects. A failed attempt therefore does not hammer the
                # Pi continuously. Changing the file enables another attempt.
                push_attempted[path] = state

                try:
                    push_background(path)

                except subprocess.CalledProcessError as error:
                    print(
                        f"Remote push failed for {path.name} "
                        f"with exit code {error.returncode}"
                    )
                    print("Modify or replace the file to retry.")

                except Exception as error:
                    print(
                        f"Remote push failed for "
                        f"{path.name}: {error}"
                    )
                    print("Modify or replace the file to retry.")

            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
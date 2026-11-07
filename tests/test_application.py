from __future__ import annotations

import json
import logging
import os
import shutil
import socket
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from random import Random
from threading import Event
from time import monotonic, sleep
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pytest
import yaml
from PIL import Image

import refrain.application as application
from refrain import (
    ApplicationError,
    ArtifactWriteError,
    DailyImagePreparationError,
    GlobalHistoryWriteError,
    NoEligibleQuotationError,
    PersistentStateStore,
    PreparedImageArtifactStore,
    StateCommitError,
    StateRecoveryError,
    run_application,
    run_startup,
)
from refrain.__main__ import main
from refrain.config import DecorationResource, DisplayBackendConfiguration
from refrain.display import (
    DisplayBackendCloseError,
    DisplayBackendInitializationError,
    DisplayBackendUpdateError,
    create_display_backend,
)
from refrain.display.coordinator import DisplayPublicationCoordinator
from refrain.information_view import InformationViewPreparationError
from refrain.qr import REPOSITORY_URL, QRCodeParameters

_ZONE = ZoneInfo("America/Toronto")
_CONFIG = """\
general:
  day_start: "06:00"
content:
  directory: "content"
reveal:
  source: "12:00"
  attribution: "18:00"
display:
  backends:
    - type: "waveshare-13in3-e"
information_view:
  duration: 0
layout:
  presentation_region: {x: 0.1, y: 0.15, width: 0.8, height: 0.55}
  fonts:
    default: ["lora"]
  text: {min_font_size: 28, max_font_size: 100}
"""


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=_ZONE)


def write_decoration_manifest(directory: Path, identifier: str, **metadata: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "id": identifier, "image": "overlay.png", **metadata}
    (directory / "decoration.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def write_font_manifest(directory: Path, identifier: str, font_name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "id": identifier, "faces": {"regular": font_name}}
    (directory / "font.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


class FakeDisplay:
    def __init__(self, *, fail_update: bool = False, fail_close: bool = False) -> None:
        self.fail_update = fail_update
        self.fail_close = fail_close
        self.sizes: list[tuple[int, int]] = []
        self.images: list[Image.Image] = []
        self.closed = 0

    def update(self, image: Image.Image) -> None:
        if self.fail_update:
            raise DisplayBackendUpdateError("update failed")
        self.sizes.append(image.size)
        self.images.append(image.copy())

    def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            raise DisplayBackendCloseError("close failed")


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = root / "config.yaml"
        self.content = root / "content"
        self.state = root / "state" / "state.json"
        self.history = self.state.with_name("global-history.jsonl")
        self.history = self.state.with_name("global-history.jsonl")
        self.artifacts = root / "artifacts"
        self.config.write_text(_CONFIG, encoding="utf-8")
        self.content.mkdir()

    def entry(self, name: str, body: str) -> None:
        (self.content / f"{name}.yaml").write_text(f'id: "{name}"\n{body}', encoding="utf-8")

    def run(self, now: datetime, display: FakeDisplay | None = None, **kwargs):
        display = display or FakeDisplay()
        result = run_startup(
            self.config,
            self.state,
            self.artifacts,
            now=now,
            random_source=Random(1),
            backend_factory=lambda configuration: display,
            **kwargs,
        )
        return result, display

    def load(self):
        return PersistentStateStore(self.state).load()

    def history_records(self):
        if not self.history.exists():
            return []
        return [json.loads(line) for line in self.history.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def ordinary(workspace: Workspace, text: str = "An ordinary quotation.", extra: str = "") -> None:
    workspace.entry("ordinary", f'source: "A Book"\nattribution: "An Author"\n{extra}quotations:\n  - "{text}"\n')


@pytest.mark.parametrize(
    ("preference", "expected"),
    [(None, "canvas"), ("cloth", "cloth"), ("none", "none"), ("unavailable-paper", "canvas")],
)
def test_background_preference_resolves_before_commit(workspace: Workspace, caplog, preference, expected) -> None:
    workspace.config.write_text(_CONFIG.replace("  fonts:", '  backgrounds:\n    default: ["canvas"]\n  fonts:'))
    ordinary(workspace, extra="" if preference is None else f'background: "{preference}"\n')
    configuration = application.load_application_config(workspace.config)
    proposal, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))
    state = PersistentStateStore(workspace.state).commit(proposal, snapshot)
    assert state.snapshot.background_identifier == expected
    assert state.snapshot.decoration_identifier == "none"
    assert dict(state.snapshot.layout["presentation_region"]) == {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55}
    assert PersistentStateStore(workspace.state).load() == state
    if preference == "unavailable-paper":
        assert "Requested background 'unavailable-paper'" in caplog.text


def test_background_pool_selects_distinct_usable_members(workspace: Workspace) -> None:
    workspace.config.write_text(
        _CONFIG.replace("  fonts:", '  backgrounds:\n    default: ["canvas", "none", "canvas", "cloth"]\n  fonts:')
    )
    configuration = application.load_application_config(workspace.config)

    class RecordingChooser:
        def choice(self, members):
            assert members == ("canvas", "none", "cloth")
            return members[-1]

    assert application._resolve_background(configuration, None, RecordingChooser()) == "cloth"


def test_decoration_preferences_resolve_before_font_background_and_region(workspace: Workspace) -> None:
    package = workspace.root / "assets" / "decorations" / "custom"
    overlay = package / "overlay.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGBA", (1600, 1200), (1, 2, 3, 128)).save(overlay)
    write_decoration_manifest(
        package,
        "custom",
        font="source-sans-3",
        background="ethereal",
        presentation_region={"x": 0.12, "y": 0.18, "width": 0.7, "height": 0.6},
    )
    workspace.config.write_text(
        _CONFIG.replace(
            "  fonts:",
            '  backgrounds: {default: ["canvas"]}\n' '  decorations: {default: ["none"]}\n' "  fonts:",
        )
    )
    ordinary(workspace, extra='decoration: "custom"\n')
    configuration = application.load_application_config(workspace.config)

    _, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))

    assert snapshot.decoration_identifier == "custom"
    assert snapshot.font_identifier == "source-sans-3"
    assert snapshot.background_identifier == "ethereal"
    assert dict(snapshot.layout["presentation_region"]) == {
        "x": 0.12,
        "y": 0.18,
        "width": 0.7,
        "height": 0.6,
    }


def test_text_color_precedence_deduplicates_candidates_and_commits_rgb(workspace: Workspace, caplog) -> None:
    package = workspace.root / "assets" / "decorations" / "custom"
    overlay = package / "overlay.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGBA", (16, 16)).save(overlay)
    write_decoration_manifest(package, "custom", text_color=["blue", "burnt-orange", "blue"])
    workspace.config.write_text(
        'palette:\n  red: "#C82F32"\n  burnt-orange: "#C65A20"\n' + _CONFIG,
        encoding="utf-8",
    )
    ordinary(
        workspace,
        extra=(
            'decoration: "custom"\n' "text_color:\n" "  - missing-color\n" "  - red\n" "  - red\n" "  - burnt-orange\n"
        ),
    )
    configuration = application.load_application_config(workspace.config)
    _, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))

    color_identifier = snapshot.presentation_metadata["text_color_identifier"]
    assert color_identifier in {"red", "burnt-orange"}
    value = configuration.palette[color_identifier]
    assert snapshot.presentation_metadata["text_color_rgb"] == (
        int(value[1:3], 16),
        int(value[3:5], 16),
        int(value[5:7], 16),
    )
    assert "missing-color" in caplog.text

    entry = application.load_content_library(workspace.content)[0]
    decoration = configuration.decorations["custom"]

    class RecordingChooser:
        members: tuple[str, ...] = ()

        def choice(self, members):
            self.members = tuple(members)
            return self.members[-1]

    chooser = RecordingChooser()
    assert application._resolve_text_color(configuration, entry, decoration, chooser) == (
        "burnt-orange",
        (198, 90, 32),
    )
    assert chooser.members == ("red", "burnt-orange")

    without_entry_preference = replace(entry, text_color=None)
    assert application._resolve_text_color(configuration, without_entry_preference, decoration, chooser)[0] == (
        "burnt-orange"
    )
    unavailable_decoration = replace(decoration, text_color=("missing-color",))
    global_preference = replace(configuration, default_text_colors=("green",))
    assert application._resolve_text_color(
        global_preference, without_entry_preference, unavailable_decoration, chooser
    ) == ("green", (0, 255, 0))
    black_fallback = replace(
        configuration,
        palette={**configuration.palette, "black": "#123456"},
        default_text_colors=("missing-color",),
    )
    assert application._resolve_text_color(
        black_fallback, without_entry_preference, unavailable_decoration, chooser
    ) == ("black", (18, 52, 86))


def test_decoration_color_precedence_uses_distinct_candidates_and_only_tints_enabled_art(
    workspace: Workspace, caplog
) -> None:
    ordinary(workspace)
    configuration = application.load_application_config(workspace.config)
    configuration = replace(
        configuration,
        palette={**configuration.palette, "burnt-orange": "#C65A20"},
        default_decoration_colors=("black", "burnt-orange"),
    )
    entry = replace(
        application.load_content_library(workspace.content)[0],
        decoration_color=("missing", "red", "red", "burnt-orange"),
    )
    decoration = DecorationResource(
        "custom",
        workspace.root / "overlay.png",
        False,
        tintable=True,
        decoration_color=("blue", "burnt-orange"),
    )

    class RecordingChooser:
        members: tuple[str, ...] = ()

        def choice(self, members):
            self.members = tuple(members)
            return self.members[-1]

    chooser = RecordingChooser()
    assert application._resolve_decoration_color(configuration, entry, decoration, chooser) == (
        "burnt-orange",
        (198, 90, 32),
    )
    assert chooser.members == ("red", "burnt-orange")
    assert "missing" in caplog.text

    without_entry_preference = replace(entry, decoration_color=None)
    assert application._resolve_decoration_color(configuration, without_entry_preference, decoration, chooser) == (
        "burnt-orange",
        (198, 90, 32),
    )
    assert chooser.members == ("blue", "burnt-orange")
    unavailable_decoration_preference = replace(decoration, decoration_color=("missing",))
    assert application._resolve_decoration_color(
        configuration, without_entry_preference, unavailable_decoration_preference, chooser
    ) == ("burnt-orange", (198, 90, 32))
    assert chooser.members == ("black", "burnt-orange")
    assert application._resolve_decoration_color(
        replace(configuration, default_decoration_colors=()),
        without_entry_preference,
        unavailable_decoration_preference,
        chooser,
    ) == ("black", (0, 0, 0))

    class RejectChoice:
        def choice(self, members):
            raise AssertionError("non-tintable decorations must not select a colour")

    assert (
        application._resolve_decoration_color(configuration, entry, replace(decoration, tintable=False), RejectChoice())
        is None
    )
    assert application._resolve_decoration_color(configuration, entry, None, RejectChoice()) is None


def test_tinting_decision_and_resolved_color_are_committed_in_snapshot(workspace: Workspace) -> None:
    package = workspace.root / "assets" / "decorations" / "custom"
    package.mkdir(parents=True)
    with Image.new("RGBA", (1600, 1200), (0, 0, 0, 0)) as decoration:
        decoration.putpixel((0, 0), (255, 255, 255, 255))
        decoration.save(package / "overlay.png")
    write_decoration_manifest(package, "custom", tintable=True, decoration_color="green")
    workspace.config.write_text(
        'palette:\n  red: "#C82F32"\n  green: "#00FF00"\n'
        + _CONFIG.replace("  fonts:", '  decorations: {default: ["none"], colors: ["black"]}\n  fonts:')
    )
    ordinary(workspace, extra='decoration: "custom"\ndecoration_color: "red"\n')

    first, first_display = workspace.run(at(10, 7))
    committed = first.state.snapshot.presentation_metadata
    assert committed["decoration_tint_enabled"] is True
    assert committed["decoration_color_identifier"] == "red"
    assert committed["decoration_color_rgb"] == (200, 47, 50)
    assert committed["text_color_identifier"] == "black"
    assert committed["text_color_rgb"] == (0, 0, 0)
    assert first_display.images[-1].getpixel((0, 0)) == (200, 47, 50)
    state_bytes = workspace.state.read_bytes()

    write_decoration_manifest(package, "custom", tintable=False, decoration_color="green")
    workspace.config.write_text('palette:\n  red: "#00FF00"\n' + _CONFIG, encoding="utf-8")
    for artifact in png_files(workspace.artifacts):
        artifact.unlink()
    second, second_display = workspace.run(at(10, 7))

    assert second.state == first.state
    assert workspace.state.read_bytes() == state_bytes
    assert second_display.images[-1].getpixel((0, 0)) == (200, 47, 50)


def test_explicit_none_and_entry_resource_preferences_override_decoration(workspace: Workspace) -> None:
    package = workspace.root / "assets" / "decorations" / "custom"
    overlay = package / "overlay.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGBA", (1600, 1200)).save(overlay)
    write_decoration_manifest(
        package,
        "custom",
        font="source-sans-3",
        background="ethereal",
        presentation_region={"x": 0.12, "y": 0.18, "width": 0.7, "height": 0.6},
    )
    workspace.config.write_text(
        _CONFIG.replace(
            "  fonts:",
            '  backgrounds: {default: ["canvas"]}\n' '  decorations: {default: ["custom"]}\n' "  fonts:",
        )
    )
    ordinary(workspace, extra='decoration: "none"\nfont: "lora"\nbackground: "none"\n')
    configuration = application.load_application_config(workspace.config)

    _, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))

    assert snapshot.decoration_identifier == "none"
    assert snapshot.font_identifier == "lora"
    assert snapshot.background_identifier == "none"
    assert dict(snapshot.layout["presentation_region"]) == {
        "x": 0.1,
        "y": 0.15,
        "width": 0.8,
        "height": 0.55,
    }


def test_role_face_precedence_falls_directly_to_regular_without_reselecting_bundle(
    workspace: Workspace, caplog
) -> None:
    source_font = Path(str(files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")))
    font_dir = workspace.root / "assets" / "fonts" / "literary"
    font_dir.mkdir(parents=True)
    shutil.copyfile(source_font, font_dir / "Regular.ttf")
    shutil.copyfile(source_font, font_dir / "Italic.ttf")
    (font_dir / "font.yaml").write_text(
        yaml.safe_dump(
            {
                "format": 1,
                "id": "literary",
                "faces": {"regular": "Regular.ttf", "italic": "Italic.ttf"},
                "font_faces": {"quotation": "italic", "source": "regular", "attribution": "italic"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    decoration_dir = workspace.root / "assets" / "decorations" / "mixed"
    decoration_dir.mkdir(parents=True)
    Image.new("RGBA", (16, 16)).save(decoration_dir / "overlay.png")
    write_decoration_manifest(
        decoration_dir,
        "mixed",
        font="lora",
        font_faces={"quotation": "italic", "source": "italic", "attribution": "italic"},
    )
    workspace.config.write_text(
        _CONFIG.replace(
            'default: ["lora"]',
            'default: ["literary"]\n    font_faces: {quotation: italic, source: italic, attribution: italic}',
        )
    )
    ordinary(
        workspace,
        extra=(
            'font: "literary"\n'
            'decoration: "mixed"\n'
            "font_faces:\n"
            "  quotation: unavailable\n"
            "  attribution: regular\n"
        ),
    )

    configuration = application.load_application_config(workspace.config)
    _, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))

    assert snapshot.font_identifier == "literary"
    assert dict(snapshot.presentation_metadata["font_faces"]) == {
        "quotation": "regular",
        "source": "italic",
        "attribution": "regular",
    }
    assert "Preferred quotation face 'unavailable'" in caplog.text


def test_bundle_and_global_face_preferences_apply_only_after_entry_and_decoration(workspace: Workspace) -> None:
    source_font = Path(str(files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")))
    font_dir = workspace.root / "assets" / "fonts" / "literary"
    font_dir.mkdir(parents=True)
    shutil.copyfile(source_font, font_dir / "Regular.ttf")
    shutil.copyfile(source_font, font_dir / "Italic.ttf")
    (font_dir / "font.yaml").write_text(
        yaml.safe_dump(
            {
                "format": 1,
                "id": "literary",
                "faces": {"regular": "Regular.ttf", "italic": "Italic.ttf"},
                "font_faces": {"quotation": "italic"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    decoration_dir = workspace.root / "assets" / "decorations" / "plain"
    decoration_dir.mkdir(parents=True)
    Image.new("RGBA", (16, 16)).save(decoration_dir / "overlay.png")
    write_decoration_manifest(decoration_dir, "plain")
    workspace.config.write_text(
        _CONFIG.replace(
            'default: ["lora"]',
            'default: ["literary"]\n    font_faces: {source: italic, attribution: italic}',
        )
    )
    ordinary(
        workspace,
        extra=('font: "literary"\n' 'decoration: "plain"\n' "font_faces:\n" "  attribution: regular\n"),
    )

    configuration = application.load_application_config(workspace.config)
    _, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))

    assert snapshot.font_identifier == "literary"
    assert dict(snapshot.presentation_metadata["font_faces"]) == {
        "quotation": "italic",
        "source": "italic",
        "attribution": "regular",
    }


def test_unavailable_explicit_decoration_falls_back_to_pool(workspace: Workspace, caplog) -> None:
    workspace.config.write_text(_CONFIG.replace("  fonts:", '  decorations: {default: ["hex"]}\n  fonts:'))
    ordinary(workspace, extra='decoration: "not-registered"\n')

    configuration = application.load_application_config(workspace.config)

    _, snapshot = application._select_snapshot(configuration, date(2026, 3, 10), Random(1))

    assert snapshot.decoration_identifier == "hex"
    assert "Requested decoration 'not-registered'" in caplog.text


def test_normal_runtime_recovers_missing_decoration_without_reselection(workspace: Workspace, caplog) -> None:
    package = workspace.root / "assets" / "decorations" / "custom"
    overlay = package / "overlay.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGBA", (1600, 1200), (200, 20, 40, 128)).save(overlay)
    write_decoration_manifest(
        package,
        "custom",
        presentation_region={"x": 0.2, "y": 0.3, "width": 0.6, "height": 0.4},
    )
    workspace.config.write_text(
        _CONFIG.replace(
            "  fonts:",
            '  decorations: {default: ["custom"]}\n' "  fonts:",
        )
    )
    ordinary(workspace)
    first, first_display = workspace.run(at(10, 7))
    snapshot = first.state.snapshot
    assert snapshot.decoration_identifier == "custom"
    assert dict(snapshot.layout["presentation_region"]) == {
        "x": 0.2,
        "y": 0.3,
        "width": 0.6,
        "height": 0.4,
    }
    assert first_display.images[-1].getpixel((10, 10)) == (227, 137, 147)

    overlay.unlink()
    for artifact in png_files(workspace.artifacts):
        artifact.unlink()
    second, second_display = workspace.run(at(10, 7))

    assert second.state == first.state
    assert dict(second.state.snapshot.layout["presentation_region"]) == dict(snapshot.layout["presentation_region"])
    assert second_display.images[-1].getpixel((10, 10)) == (255, 255, 255)
    assert "Committed decoration 'custom' is unavailable" in caplog.text


def test_committed_background_survives_restart_config_changes_and_resource_loss(workspace: Workspace, caplog) -> None:
    path = workspace.root / "assets" / "backgrounds" / "paper.png"
    path.parent.mkdir(parents=True)
    with Image.new("RGB", (1600, 1200), (100, 140, 180)) as image:
        image.save(path)
    workspace.config.write_text(
        _CONFIG.replace(
            "  fonts:",
            '  backgrounds:\n    default: ["paper"]\n  fonts:',
        )
    )
    ordinary(workspace)
    first, first_display = workspace.run(at(10, 7))
    assert first.state.snapshot.background_identifier == "paper"
    assert first_display.images[-1].getpixel((0, 0)) == (100, 140, 180)
    path.unlink()
    workspace.config.write_text(_CONFIG.replace("  fonts:", '  backgrounds:\n    default: ["canvas"]\n  fonts:'))
    second, second_display = workspace.run(at(10, 7))
    assert second.state == first.state
    assert second_display.images[-1].tobytes() == first_display.images[-1].tobytes()
    for artifact in png_files(workspace.artifacts):
        artifact.unlink()
    third, third_display = workspace.run(at(10, 7))
    assert third.state == first.state
    assert third_display.images[-1].getpixel((0, 0)) == (255, 255, 255)
    assert "Committed background 'paper'" in caplog.text


def test_committed_text_color_survives_palette_changes_and_artifact_regeneration(workspace: Workspace) -> None:
    workspace.config.write_text('palette:\n  red: "#C82F32"\n' + _CONFIG, encoding="utf-8")
    ordinary(workspace, extra="text_color: red\n")

    first, first_display = workspace.run(at(10, 7))
    committed = first.state.snapshot.presentation_metadata
    assert committed["text_color_identifier"] == "red"
    assert committed["text_color_rgb"] == (200, 47, 50)
    assert (200, 47, 50) in first_display.images[-1].get_flattened_data()
    state_bytes = workspace.state.read_bytes()

    workspace.config.write_text('palette:\n  red: "#00FF00"\n' + _CONFIG, encoding="utf-8")
    for artifact in png_files(workspace.artifacts):
        artifact.unlink()
    second, second_display = workspace.run(at(10, 7))

    assert second.state == first.state
    assert workspace.state.read_bytes() == state_bytes
    assert second_display.images[-1].tobytes() == first_display.images[-1].tobytes()
    assert (200, 47, 50) in second_display.images[-1].get_flattened_data()
    assert (0, 255, 0) not in second_display.images[-1].get_flattened_data()


def png_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.png"))


def test_first_startup_commits_snapshot_and_presents(workspace: Workspace) -> None:
    ordinary(workspace)
    result, display = workspace.run(at(10, 7))

    state = workspace.load()
    assert result.selected_initial_quotation and result.presented_stage == 0
    assert state is not None and state.revision == 1 and state.highest_reveal_stage == 0
    snapshot = state.snapshot
    assert snapshot.quotation_text == "An ordinary quotation."
    assert snapshot.font_identifier == "lora"
    assert snapshot.display_date == date(2026, 3, 10)
    assert snapshot.presentation_metadata == {
        "presentation_style": "centered",
        "source": "A Book",
        "attribution": "An Author",
        "font_faces": {"quotation": "regular", "source": "regular", "attribution": "regular"},
        "text_color_identifier": "black",
        "text_color_rgb": (0, 0, 0),
        "decoration_tint_enabled": False,
        "qr_code": {
            "url": "https://github.com/ControlForgeHQ/refrain",
            "version": 4,
            "error_correction": "M",
            "module_size": 3,
            "quiet_zone": 4,
            "right_offset": 40,
            "bottom_offset": 40,
        },
    }
    assert dict(snapshot.reveal_schedule) == {"quotation": "06:00", "source": "12:00", "attribution": "18:00"}
    assert snapshot.layout["image_size"] == (1600, 1200) or list(snapshot.layout["image_size"]) == [1600, 1200]
    assert state.repetition_history == {snapshot.quotation_identity}
    assert len(workspace.history_records()) == 1
    assert display.sizes == [(1600, 1200)] and display.closed == 1
    assert display.images[0].getpixel((1437, 1037)) == (255, 255, 255)
    assert display.images[0].getpixel((1449, 1049)) == (0, 0, 0)
    assert len(png_files(workspace.artifacts)) == 3


def test_snapshot_accepts_an_explicit_internal_qr_url(workspace: Workspace) -> None:
    ordinary(workspace)
    configuration = application.load_application_config(workspace.config)
    entry = application.load_content_library(configuration.content_directory)[0]
    snapshot = application._build_snapshot(
        configuration,
        entry,
        entry.quotations[0],
        date(2026, 3, 10),
        Random(1),
        qr_parameters=QRCodeParameters("https://example.org/quote", 4, "M", 3, 4, 40, 40),
    )

    assert snapshot.presentation_metadata["qr_code"]["url"] == "https://example.org/quote"
    assert snapshot.presentation_metadata["qr_code"]["url"] != REPOSITORY_URL


def test_debug_layout_only_changes_published_copy_of_cached_image(workspace: Workspace) -> None:
    ordinary(workspace)
    _, baseline_display = workspace.run(at(10, 7))
    cached = {path: path.read_bytes() for path in png_files(workspace.artifacts)}
    committed = workspace.load()

    _, debug_display = workspace.run(at(10, 7), debug_layout=True)

    assert baseline_display.images[0].getpixel((160, 300)) == (255, 255, 255)
    assert debug_display.images[0].getpixel((160, 300)) == (127, 127, 127)
    assert {path: path.read_bytes() for path in png_files(workspace.artifacts)} == cached
    assert workspace.load() == committed
    for display in (baseline_display, debug_display):
        for image in display.images:
            image.close()


def test_debug_layout_uses_committed_region_after_configuration_and_manifest_change(workspace: Workspace) -> None:
    package = workspace.root / "assets" / "decorations" / "custom"
    package.mkdir(parents=True)
    Image.new("RGBA", (1600, 1200), (0, 0, 0, 0)).save(package / "overlay.png")
    write_decoration_manifest(
        package,
        "custom",
        presentation_region={"x": 0.2, "y": 0.3, "width": 0.6, "height": 0.4},
    )
    ordinary(workspace, extra='decoration: "custom"\n')
    _, baseline_display = workspace.run(at(10, 7))
    committed = workspace.load()

    workspace.config.write_text(
        workspace.config.read_text(encoding="utf-8").replace(
            "x: 0.1, y: 0.15, width: 0.8, height: 0.55",
            "x: 0.3, y: 0.4, width: 0.4, height: 0.3",
        ),
        encoding="utf-8",
    )
    write_decoration_manifest(
        package,
        "custom",
        presentation_region={"x": 0.4, "y": 0.5, "width": 0.5, "height": 0.4},
    )
    _, debug_display = workspace.run(at(10, 7), debug_layout=True)

    assert committed.snapshot.layout["presentation_region"] == {
        "x": 0.2,
        "y": 0.3,
        "width": 0.6,
        "height": 0.4,
    }
    assert baseline_display.images[0].getpixel((320, 450)) == (255, 255, 255)
    assert debug_display.images[0].getpixel((320, 450)) == (127, 127, 127)
    assert workspace.load() == committed
    for display in (baseline_display, debug_display):
        for image in display.images:
            image.close()


def test_one_shot_debug_layout_only_outlines_the_daily_presentation(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.config.write_text(workspace.config.read_text(encoding="utf-8").replace("duration: 0", "duration: 1"))
    prepared_information = []
    prepare_information = application.prepare_information_view

    def capture_information(configuration):
        image = prepare_information(configuration)
        prepared_information.append(image.copy())
        return image

    monkeypatch.setattr(application, "prepare_information_view", capture_information)

    result, display = workspace.run(at(10, 7), debug_layout=True)

    assert result.state.revision == 1
    assert display.sizes == [(1600, 1200), (1600, 1200)]
    assert display.images[0].tobytes() != display.images[1].tobytes()
    assert display.images[0].tobytes() == prepared_information[0].tobytes()
    assert display.images[1].getpixel((160, 300)) == (127, 127, 127)
    assert len(workspace.history_records()) == 1
    prepared_information[0].close()
    for image in display.images:
        image.close()


def test_one_shot_startup_advances_reveal_due_during_information_interval(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.config.write_text(workspace.config.read_text(encoding="utf-8").replace("duration: 0", "duration: 60"))
    elapsed = [0.0]
    current_time = [at(10, 11, 59)]

    def wait(duration: float) -> None:
        elapsed[0] += duration
        current_time[0] = at(10, 12, 1)

    result, display = workspace.run(
        at(10, 11, 59),
        wall_clock=lambda: current_time[0],
        monotonic_clock=lambda: elapsed[0],
        wait=wait,
    )

    state = workspace.load()
    assert result.presented_stage == 1
    assert state.highest_reveal_stage == 1
    assert [image.size for image in display.images] == [(1600, 1200), (1600, 1200)]
    assert display.images[0].tobytes() != display.images[1].tobytes()
    assert state.revision == 1 and len(workspace.history_records()) == 1


def test_nondefault_day_start_sets_initial_snapshot_reveal_time(workspace: Workspace, caplog) -> None:
    ordinary(workspace)
    workspace.config.write_text(
        _CONFIG.replace('day_start: "06:00"', 'day_start: "08:00"').replace(
            "reveal:\n  source:", 'reveal:\n  quotation: "00:00"\n  source:'
        ),
        encoding="utf-8",
    )

    result, _ = workspace.run(at(10, 8, 30))

    state = workspace.load()
    assert result.presented_stage == 0
    assert state is not None
    assert state.snapshot.reveal_schedule["quotation"] == "08:00"
    assert "reveal.quotation" in caplog.text


def test_startup_publishes_one_prepared_image_to_all_configured_backends(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.config.write_text(
        workspace.config.read_text(encoding="utf-8").replace(
            '    - type: "waveshare-13in3-e"',
            '    - type: "window"\n    - type: "image-server"',
        ),
        encoding="utf-8",
    )
    displays = {"window": FakeDisplay(), "image-server": FakeDisplay()}

    def factory(configuration):
        return displays[configuration.type]

    result = run_startup(
        workspace.config,
        workspace.state,
        workspace.artifacts,
        debug_layout=True,
        now=at(10, 7),
        random_source=Random(1),
        backend_factory=factory,
    )

    assert result.state.revision == 1
    assert all(display.sizes == [(1600, 1200)] and display.closed == 1 for display in displays.values())
    assert displays["window"].images[0].tobytes() == displays["image-server"].images[0].tobytes()
    assert displays["window"].images[0].getpixel((160, 300)) == (127, 127, 127)
    for display in displays.values():
        for image in display.images:
            image.close()


def test_history_write_failure_does_not_interrupt_startup_presentation(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    ordinary(workspace)
    monkeypatch.setattr(
        application.GlobalHistoryStore,
        "record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(GlobalHistoryWriteError("disk unavailable")),
    )

    result, display = workspace.run(at(10, 7))

    assert result.state.revision == 1
    assert display.sizes == [(1600, 1200)]
    assert len(png_files(workspace.artifacts)) == 3
    assert "was not recorded in global history" in caplog.text


def test_history_paths_cannot_overwrite_operational_state(workspace: Workspace) -> None:
    with pytest.raises(ValueError, match="must not overlap the operational state"):
        application._create_history_store(workspace.state, workspace.state, 1_048_576, 20)
    with pytest.raises(ValueError, match="must not overlap the operational state"):
        application._create_history_store(
            workspace.state.with_name("global-history.jsonl"),
            None,
            1_048_576,
            20,
        )
    with pytest.raises(ValueError, match="must not overlap the operational state"):
        application._create_history_store(
            workspace.state.with_name("global-history.1.jsonl"),
            workspace.state.with_name("global-history.jsonl"),
            1_048_576,
            20,
        )


def test_selection_prunes_only_identities_absent_from_effective_library(workspace: Workspace) -> None:
    ordinary(workspace, "Current quotation.")
    workspace.run(at(10, 8))
    state = workspace.load()
    workspace.entry(
        "ineligible-a",
        'eligibility:\n  - month: 4\nquotations:\n  - "Temporarily ineligible."\n',
    )
    workspace.entry(
        "ineligible-b",
        'eligibility:\n  - month: 5\nquotations:\n  - "Temporarily ineligible."\n',
    )
    workspace.entry("rejected", 'unknown: true\nquotations:\n  - "Rejected quotation."\n')
    state = replace(
        state,
        repetition_history=frozenset(
            {
                state.snapshot.quotation_identity,
                "Temporarily ineligible.",
                "Removed from library.",
                "Rejected quotation.",
            }
        ),
    )
    configuration = application.load_application_config(workspace.config)

    proposal, snapshot = application._select_snapshot(configuration, date(2026, 3, 11), Random(1), state)

    assert "Removed from library." not in proposal.proposed_repetition_history
    assert "Rejected quotation." not in proposal.proposed_repetition_history
    assert "Temporarily ineligible." in proposal.proposed_repetition_history
    assert len(proposal.proposed_repetition_history) == 2
    assert state.repetition_history == {
        state.snapshot.quotation_identity,
        "Temporarily ineligible.",
        "Removed from library.",
        "Rejected quotation.",
    }
    committed = PersistentStateStore(workspace.state).commit(proposal, snapshot)
    assert committed.repetition_history == proposal.proposed_repetition_history

    for path in workspace.content.iterdir():
        path.unlink()
    ordinary(workspace, "Removed from library.")
    restored, _ = application._select_snapshot(configuration, date(2026, 3, 12), Random(1), committed)
    assert restored.selected_candidate.text == "Removed from library."


def test_startup_before_day_start_uses_previous_display_date(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 5, 30))
    state = workspace.load()
    assert state.snapshot.display_date == date(2026, 3, 9)


def test_date_specific_entry_takes_precedence(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 10\nquotations:\n  - "A special quotation."\n')
    workspace.run(at(10, 8))
    assert workspace.load().snapshot.quotation_text == "A special quotation."


def test_multiple_quotations_select_one_and_record_history(workspace: Workspace) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n  - "Third."\n')
    workspace.run(at(10, 8))
    state = workspace.load()
    assert state.snapshot.quotation_text in {"First.", "Second.", "Third."}
    assert state.repetition_history == {state.snapshot.quotation_identity}


def test_entry_font_preference_is_resolved(workspace: Workspace) -> None:
    ordinary(workspace, extra='font: "source-sans-3"\n')
    workspace.run(at(10, 8))
    assert workspace.load().snapshot.font_identifier == "source-sans-3"


def test_empty_effective_font_pool_blocks_only_new_selection(workspace: Workspace) -> None:
    config = workspace.config.read_text(encoding="utf-8").replace(
        'default: ["lora"]',
        'default: ["missing-font"]',
    )
    workspace.config.write_text(config, encoding="utf-8")
    ordinary(workspace)

    with pytest.raises(ApplicationError, match="no usable font remains"):
        workspace.run(at(10, 8))
    assert workspace.load() is None


def test_committed_custom_font_recovers_without_registry_and_regenerates_with_bundled_fallback(
    workspace: Workspace, caplog
) -> None:
    package = workspace.root / "assets" / "fonts" / "custom-font"
    custom_font = package / "custom.ttf"
    custom_font.parent.mkdir(parents=True)
    bundled_font = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
    custom_font.write_bytes(bundled_font.read_bytes())
    write_font_manifest(package, "custom-font", "custom.ttf")
    config = workspace.config.read_text(encoding="utf-8").replace(
        'default: ["lora"]',
        'default: ["custom-font"]',
    )
    workspace.config.write_text(config, encoding="utf-8")
    ordinary(workspace, extra='font: "custom-font"\n')
    first, _ = workspace.run(at(10, 8))
    committed_bytes = workspace.state.read_bytes()
    assert first.state.snapshot.font_identifier == "custom-font"

    custom_font.unlink()
    with caplog.at_level(logging.WARNING):
        recovered, _ = workspace.run(at(10, 9))
    assert not recovered.selected_initial_quotation
    assert "custom-font" in caplog.text
    assert workspace.state.read_bytes() == committed_bytes

    png_files(workspace.artifacts)[0].write_bytes(b"damaged image")
    with caplog.at_level(logging.WARNING):
        regenerated, _ = workspace.run(at(10, 9))
    assert not regenerated.selected_initial_quotation
    assert "bundled fallback" in caplog.text
    assert workspace.load() == first.state
    assert workspace.state.read_bytes() == committed_bytes


def test_unavailable_font_falls_back_to_default_pool(workspace: Workspace, caplog) -> None:
    ordinary(workspace, extra='font: "missing-font"\n')
    with caplog.at_level(logging.WARNING):
        workspace.run(at(10, 8))
    assert workspace.load().snapshot.font_identifier == "lora"
    assert "missing-font" in caplog.text


def test_reveal_overrides_and_simultaneous_reveals(workspace: Workspace) -> None:
    ordinary(workspace, extra='reveal:\n  source: "10:00"\n  attribution: "10:00"\n')
    result, display = workspace.run(at(10, 10, 30))
    assert dict(workspace.load().snapshot.reveal_schedule) == {
        "quotation": "06:00",
        "source": "10:00",
        "attribution": "10:00",
    }
    assert result.presented_stage == 1
    assert len(png_files(workspace.artifacts)) == 2


def test_attribution_can_reveal_before_source(workspace: Workspace) -> None:
    ordinary(workspace, extra='reveal:\n  attribution: "09:00"\n')
    result, _ = workspace.run(at(10, 9, 30))
    assert result.presented_stage == 1
    assert len(png_files(workspace.artifacts)) == 3


def test_invalid_override_before_day_start_commits_nothing(workspace: Workspace) -> None:
    ordinary(workspace, extra='reveal:\n  source: "05:00"\n')
    with pytest.raises(ApplicationError, match="daily snapshot"):
        workspace.run(at(10, 8))
    assert workspace.load() is None


def test_startup_after_reveal_times_presents_latest_stage(workspace: Workspace) -> None:
    ordinary(workspace)
    result, display = workspace.run(at(10, 19))
    assert result.presented_stage == 2
    assert workspace.load().highest_reveal_stage == 2
    assert workspace.load().revision == 1


def test_repeated_startup_preserves_selection_and_artifacts(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n  - "Third."\n')
    workspace.run(at(10, 8))
    first = workspace.load()
    state_bytes = workspace.state.read_bytes()
    artifact_times = {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)}

    def fail(*args, **kwargs):
        raise AssertionError("valid artifacts must not be regenerated")

    monkeypatch.setattr("refrain.recovery.prepare_daily_images", fail)
    result, display = workspace.run(at(10, 9))
    assert not result.selected_initial_quotation
    assert workspace.load() == first
    assert workspace.state.read_bytes() == state_bytes
    assert {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)} == artifact_times
    assert len(display.sizes) == 1


def test_calendar_mismatch_and_missing_content_do_not_reselect(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    first = workspace.load()
    for path in workspace.content.iterdir():
        path.unlink()
    workspace.content.rmdir()
    result, display = workspace.run(at(14, 9))
    state = workspace.load()
    assert (state.revision, state.snapshot, state.repetition_history) == (
        first.revision,
        first.snapshot,
        first.repetition_history,
    )
    assert result.presented_stage == 2
    assert len(display.sizes) == 1


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_artifacts_are_recovered(workspace: Workspace, damage: str) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    first = workspace.load()
    if damage == "missing":
        for path in png_files(workspace.artifacts):
            path.unlink()
    else:
        png_files(workspace.artifacts)[0].write_bytes(b"not a png")
    _, display = workspace.run(at(10, 9))
    assert workspace.load() == first
    assert display.sizes == [(1600, 1200)]
    assert len(png_files(workspace.artifacts)) >= 3


def test_backward_clock_does_not_hide_reached_stage(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 19))
    result, display = workspace.run(at(10, 7))
    assert result.presented_stage == 2
    reference = workspace.run(at(10, 19))[1]
    assert display.images[0].tobytes() == reference.images[0].tobytes()
    result, _ = workspace.run(at(9, 7))
    assert result.presented_stage == 2


def test_no_eligible_content_commits_nothing(workspace: Workspace) -> None:
    workspace.entry("other", 'eligibility:\n  - month: 7\nquotations:\n  - "Summer."\n')
    with pytest.raises(NoEligibleQuotationError):
        workspace.run(at(10, 8))
    assert workspace.load() is None and not workspace.artifacts.exists()


def test_invalid_content_is_excluded_and_invalid_configuration_remains_fatal(workspace: Workspace, caplog) -> None:
    ordinary(workspace)
    (workspace.content / "bad.yaml").write_text("id: 5\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        result, _ = workspace.run(at(10, 8))
    assert result.selected_initial_quotation
    assert "bad.yaml" in caplog.text
    assert workspace.load().revision == 1

    workspace.config.write_text("display: {backend: nope}\n", encoding="utf-8")
    with pytest.raises(ApplicationError, match="configuration"):
        workspace.run(at(10, 8))
    assert workspace.load().revision == 1


def test_invalid_state_is_reported(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.state.parent.mkdir()
    workspace.state.write_text("garbage", encoding="utf-8")
    with pytest.raises(ApplicationError, match="persistent state"):
        workspace.run(at(10, 8))
    assert workspace.state.read_text(encoding="utf-8") == "garbage"


def test_naive_timestamp_is_rejected(workspace: Workspace) -> None:
    ordinary(workspace)
    with pytest.raises(ApplicationError, match="scheduling"):
        workspace.run(datetime(2026, 3, 10, 8))


def test_default_timestamp_is_used_when_omitted(workspace: Workspace) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    run_startup(workspace.config, workspace.state, workspace.artifacts, backend_factory=lambda c: display)
    assert workspace.load().revision == 1


def test_display_initialization_failure_preserves_state(workspace: Workspace) -> None:
    ordinary(workspace)

    def factory(configuration):
        raise DisplayBackendInitializationError("no display")

    with pytest.raises(ApplicationError, match="all configured display destinations"):
        run_startup(workspace.config, workspace.state, workspace.artifacts, now=at(10, 8), backend_factory=factory)
    state = workspace.load()
    assert state.revision == 1 and state.highest_reveal_stage == 0
    result, _ = workspace.run(at(10, 8))
    assert not result.selected_initial_quotation and workspace.load() == state


def test_display_update_failure_closes_backend_and_persists_required_reveal(workspace: Workspace) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)
    with pytest.raises(ApplicationError, match="all configured display destinations"):
        workspace.run(at(10, 19), display)
    assert display.closed == 1
    state = workspace.load()
    assert state.revision == 1 and state.highest_reveal_stage == 2
    result, _ = workspace.run(at(10, 19))
    assert result.presented_stage == 2 and workspace.load().revision == 1


def test_display_close_failure_is_reported_without_reselection(workspace: Workspace, caplog) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8), FakeDisplay(fail_close=True))
    assert workspace.load().revision == 1
    assert "cleanup failed" in caplog.text


def test_loaded_images_are_closed(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    closed: list[Image.Image] = []
    original = Image.Image.close

    def tracking_close(self):
        closed.append(self)
        return original(self)

    workspace.run(at(10, 8))
    monkeypatch.setattr(Image.Image, "close", tracking_close)
    display = FakeDisplay()
    workspace.run(at(10, 8), display)
    assert closed


def test_artifact_failure_preserves_selection(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.artifacts.parent.mkdir(exist_ok=True)
    workspace.artifacts.write_text("a file, not a directory", encoding="utf-8")
    with pytest.raises(ApplicationError, match="artifact"):
        workspace.run(at(10, 8))
    assert workspace.load().revision == 1


def test_uncertain_commit_publication_is_resolved_by_reloading(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit

    def commit(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise StateCommitError("durability unconfirmed", published=True)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    result, _ = workspace.run(at(10, 8))
    assert result.state.revision == 1 and len(workspace.history_records()) == 1


def test_unpublished_commit_failure_is_reported(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)

    def commit(self, *args, **kwargs):
        raise StateCommitError("disk full")

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    with pytest.raises(ApplicationError, match="disk full"):
        workspace.run(at(10, 8))
    assert workspace.load() is None


def test_uncertain_reveal_progress_publication_is_resolved_by_reloading(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    original = PersistentStateStore.advance_reveal_progress

    def advance(self, revision, stage):
        original(self, revision, stage)
        raise StateCommitError("durability unconfirmed", published=True)

    monkeypatch.setattr(PersistentStateStore, "advance_reveal_progress", advance)
    result, _ = workspace.run(at(10, 19))
    assert result.state.highest_reveal_stage == 2 and workspace.load().revision == 1


def test_failed_reveal_progress_update_is_reported(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))

    def advance(self, revision, stage):
        raise StateCommitError("disk full")

    monkeypatch.setattr(PersistentStateStore, "advance_reveal_progress", advance)
    display = FakeDisplay()
    with pytest.raises(ApplicationError, match="reveal progress"):
        workspace.run(at(10, 19), display)
    assert display.closed == 0 and workspace.load().highest_reveal_stage == 0


def test_keep_open_runs_before_backend_is_closed(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.config.write_text(
        workspace.config.read_text(encoding="utf-8").replace(
            'type: "waveshare-13in3-e"',
            'type: "window"',
        ),
        encoding="utf-8",
    )
    display = FakeDisplay()
    seen: list[tuple[str, int]] = []
    workspace.run(at(10, 8), display, keep_open=lambda backend: seen.append((backend, display.closed)))
    assert seen == [("window", 0)] and display.closed == 1


def test_command_line_runs_startup(workspace: Workspace, monkeypatch, capsys) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    monkeypatch.setattr(application, "create_display_backend", lambda *args, **kwargs: display)
    arguments = [
        "--once",
        "--config",
        str(workspace.config),
        "--state",
        str(workspace.state),
        "--artifacts",
        str(workspace.artifacts),
    ]
    assert main(arguments) == 0
    assert "Selected selection 1" in capsys.readouterr().out
    assert main(arguments) == 0
    assert "Recovered selection 1" in capsys.readouterr().out
    assert workspace.load().revision == 1 and display.closed == 2


def test_command_line_reports_errors(workspace: Workspace, capsys) -> None:
    code = main(["--config", str(workspace.root / "nope.yaml"), "--state", "s.json", "--artifacts", "a"])
    assert code == 1
    assert "refrain:" in capsys.readouterr().err


class RuntimeClock(Event):
    """Controlled clocks and interruptible waits; no real elapsed time."""

    def __init__(self, now: datetime, events=(), retries=()) -> None:
        super().__init__()
        self.now = now
        self.elapsed = 0.0
        self.events = iter(events)
        self.retries = iter(retries)
        self.deadlines: list[datetime] = []
        self.retry_delays: list[float] = []

    def move(self, now: datetime) -> None:
        difference = (now.astimezone(timezone.utc) - self.now.astimezone(timezone.utc)).total_seconds()
        self.elapsed += max(1.0, difference)
        self.now = now

    def scheduling_wait(self, deadline, shutdown, **kwargs):
        assert shutdown is self
        self.deadlines.append(deadline)
        event = next(self.events, None)
        if callable(event):
            event()
        elif event is None:
            self.set()
        else:
            self.move(event)
        return self.is_set()

    def wait(self, timeout=None):
        assert timeout is not None and 0 < timeout <= 300
        self.retry_delays.append(timeout)
        self.elapsed += timeout
        self.now += timedelta(seconds=timeout)
        callback = next(self.retries, None)
        if callback is not None:
            callback()
        else:
            self.set()
        return self.is_set()


def run_continuously(workspace, clock, monkeypatch, display=None, **kwargs):
    display = display or FakeDisplay()
    presentations = []
    initializations = []
    coordinators = []

    class TrackingCoordinator(application.DisplayPublicationCoordinator):
        def __init__(self, *args, **coordinator_kwargs):
            super().__init__(*args, **coordinator_kwargs)
            self.requested = []
            coordinators.append(self)

        def publish(self, identity, image):
            self.requested.append(identity)
            presentations.append(identity)
            super().publish(identity, image)

    def initialize(configuration):
        initializations.append(configuration.type)
        return display

    with monkeypatch.context() as patch:
        patch.setattr(application, "DisplayPublicationCoordinator", TrackingCoordinator)
        run_application(
            workspace.config,
            workspace.state,
            workspace.artifacts,
            shutdown_event=clock,
            wall_clock=lambda: clock.now,
            monotonic_clock=lambda: clock.elapsed,
            scheduling_wait=kwargs.pop("scheduling_wait", clock.scheduling_wait),
            random_source=Random(1),
            backend_factory=kwargs.pop("backend_factory", initialize),
            **kwargs,
        )
    return presentations, initializations, display


def install_recording_coordinator(monkeypatch, *, acknowledge_information_view: bool):
    instances = []

    class RecordingCoordinator:
        def __init__(self, *_args, **_kwargs):
            self.desired_identity = None
            self.requested = []
            self.acknowledged = set()
            self.closed = False
            self.all_unavailable = False
            instances.append(self)

        def publish(self, identity, image):
            self.requested.append(identity)
            self.desired_identity = identity
            image.close()
            if acknowledge_information_view and identity == application._INFORMATION_VIEW_IDENTITY:
                self.acknowledged.add(identity)

        def has_successful_publication(self, identity):
            return identity in self.acknowledged

        def first_successful_publication_time(self, identity):
            return 0.0 if identity in self.acknowledged else None

        def clear_desired(self):
            self.desired_identity = None

        def close(self):
            self.closed = True

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", RecordingCoordinator)
    return instances


def test_information_interval_uses_monotonic_time_across_wall_clock_adjustments(
    workspace: Workspace, monkeypatch, caplog
) -> None:
    ordinary(workspace)
    caplog.set_level(logging.INFO)
    workspace.config.write_text(workspace.config.read_text(encoding="utf-8").replace("duration: 0", "duration: 2"))
    coordinators = install_recording_coordinator(monkeypatch, acknowledge_information_view=True)
    clock = RuntimeClock(at(10, 7))
    waits = 0

    def scheduling_wait(_deadline, _shutdown, **_kwargs):
        nonlocal waits
        waits += 1
        if waits == 1:
            clock.now -= timedelta(hours=1)
            clock.elapsed += 0.5
        elif waits == 2:
            clock.now += timedelta(hours=2)
            clock.elapsed += 1.4
        elif waits == 3:
            clock.elapsed += 0.1
        else:
            clock.set()
        return clock.is_set()

    run_application(
        workspace.config,
        workspace.state,
        workspace.artifacts,
        shutdown_event=clock,
        random_source=Random(1),
        wall_clock=lambda: clock.now,
        monotonic_clock=lambda: clock.elapsed,
        scheduling_wait=scheduling_wait,
    )

    assert coordinators[0].requested == [(0, -1), (1, 0)]
    assert clock.elapsed == 2
    assert workspace.load().revision == 1
    assert len(workspace.history_records()) == 1
    assert caplog.text.count("Information view publication acknowledged") == 1


def test_bounded_information_attempt_transitions_to_current_day_and_reveal(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.config.write_text(workspace.config.read_text(encoding="utf-8").replace("duration: 0", "duration: 60"))
    coordinators = install_recording_coordinator(monkeypatch, acknowledge_information_view=False)
    clock = RuntimeClock(at(10, 7))
    waits = 0

    def scheduling_wait(_deadline, _shutdown, **_kwargs):
        nonlocal waits
        waits += 1
        if waits == 1:
            clock.elapsed += 60
            clock.now = at(11, 19)
        else:
            clock.set()
        return clock.is_set()

    run_application(
        workspace.config,
        workspace.state,
        workspace.artifacts,
        shutdown_event=clock,
        random_source=Random(1),
        wall_clock=lambda: clock.now,
        monotonic_clock=lambda: clock.elapsed,
        scheduling_wait=scheduling_wait,
    )

    state = workspace.load()
    assert coordinators[0].requested == [(0, -1), (2, 2)]
    assert state.revision == 2 and state.highest_reveal_stage == 2
    assert state.snapshot.display_date == date(2026, 3, 11)
    assert len(workspace.history_records()) == 2


def test_information_view_timer_starts_on_first_backend_ack_and_transitions_latest_daily_image(
    workspace: Workspace,
) -> None:
    ordinary(workspace)
    workspace.config.write_text(
        workspace.config.read_text(encoding="utf-8")
        .replace("duration: 0", "duration: 2")
        .replace(
            '    - type: "waveshare-13in3-e"',
            '    - type: "window"\n    - type: "image-server"',
        ),
        encoding="utf-8",
    )
    clock = RuntimeClock(at(10, 7))
    allow_fast_update, slow_started, release_slow, slow_daily = Event(), Event(), Event(), Event()

    class FastDisplay(FakeDisplay):
        def update(self, image: Image.Image) -> None:
            if not self.images:
                assert allow_fast_update.wait(5)
            super().update(image)

    fast = FastDisplay()

    class SlowDisplay(FakeDisplay):
        def update(self, image: Image.Image) -> None:
            if not self.images:
                slow_started.set()
                assert release_slow.wait(5)
            super().update(image)
            if len(self.images) == 2:
                slow_daily.set()

    slow = SlowDisplay()
    displays = {"window": fast, "image-server": slow}
    wait_count = 0

    def scheduling_wait(_deadline, wake_event, **_kwargs):
        nonlocal wait_count
        wait_count += 1
        if wait_count == 1:
            assert slow_started.wait(2)
            allow_fast_update.set()
            assert wake_event.wait(2)
            return False
        if wait_count == 2:
            assert wake_event is clock
            clock.elapsed += 2
            clock.now = at(11, 19)
            return False
        release_slow.set()
        assert slow_daily.wait(2)
        clock.set()
        return True

    try:
        run_application(
            workspace.config,
            workspace.state,
            workspace.artifacts,
            shutdown_event=clock,
            random_source=Random(1),
            backend_factory=lambda configuration: displays[configuration.type],
            wall_clock=lambda: clock.now,
            monotonic_clock=lambda: clock.elapsed,
            scheduling_wait=scheduling_wait,
        )
    finally:
        release_slow.set()

    assert len(fast.images) == len(slow.images) == 2
    assert fast.images[0].tobytes() == slow.images[0].tobytes()
    assert fast.images[1].tobytes() == slow.images[1].tobytes()
    assert fast.images[0].tobytes() != fast.images[1].tobytes()
    assert workspace.load().revision == 2
    assert workspace.load().highest_reveal_stage == 2
    assert workspace.load().snapshot.display_date == date(2026, 3, 11)
    assert len(workspace.history_records()) == 2


def test_information_view_preparation_failure_falls_back_to_daily_presentation(
    workspace: Workspace, monkeypatch
) -> None:
    ordinary(workspace)
    workspace.config.write_text(workspace.config.read_text(encoding="utf-8").replace("duration: 0", "duration: 60"))
    monkeypatch.setattr(
        application,
        "prepare_information_view",
        lambda _configuration: (_ for _ in ()).throw(InformationViewPreparationError("render failed")),
    )
    clock = RuntimeClock(at(10, 7))
    display = FakeDisplay()

    def wait_for_daily_image(_deadline, _shutdown, **_kwargs):
        deadline = monotonic() + 2
        while not display.sizes and monotonic() < deadline:
            sleep(0.01)
        assert display.sizes == [(1600, 1200)]
        clock.set()
        return True

    stages, _, _ = run_continuously(workspace, clock, monkeypatch, display, scheduling_wait=wait_for_daily_image)

    assert stages == [(1, 0)]
    assert display.sizes == [(1600, 1200)]
    assert workspace.load().revision == 1
    assert len(workspace.history_records()) == 1


def test_shutdown_during_information_publication_releases_backend_safely(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.config.write_text(workspace.config.read_text(encoding="utf-8").replace("duration: 0", "duration: 300"))
    clock = RuntimeClock(at(10, 7))
    started, release = Event(), Event()

    class BlockingDisplay(FakeDisplay):
        def update(self, image: Image.Image) -> None:
            started.set()
            assert release.wait(5)
            super().update(image)

    display = BlockingDisplay()

    def scheduling_wait(_deadline, _shutdown, **_kwargs):
        assert started.wait(2)
        release.set()
        clock.set()
        return True

    run_application(
        workspace.config,
        workspace.state,
        workspace.artifacts,
        shutdown_event=clock,
        random_source=Random(1),
        backend_factory=lambda _configuration: display,
        wall_clock=lambda: clock.now,
        monotonic_clock=lambda: clock.elapsed,
        scheduling_wait=scheduling_wait,
    )

    assert len(display.images) == 1 and display.closed == 1
    assert workspace.load().revision == 1
    assert len(workspace.history_records()) == 1


def test_continuous_reveals_reuse_artifacts_and_one_backend(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = application.recover_prepared_daily_images
    recovered = []

    def recover(state, *args):
        recovered.append(state.revision)
        return original(state, *args)

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)

    def forbid_content_reload():
        monkeypatch.setattr(application, "load_content_library", lambda *args: pytest.fail("content reloaded"))
        clock.move(at(10, 12))

    clock = RuntimeClock(at(10, 7), [forbid_content_reload, at(10, 18), at(10, 19)])
    stages, initialized, display = run_continuously(workspace, clock, monkeypatch, debug_layout=True)
    assert stages == [(1, 0), (1, 1), (1, 2)]
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1
    assert len(png_files(workspace.artifacts)) == 3
    assert recovered == [1]
    assert clock.deadlines[:2] == [at(10, 12), at(10, 18)]
    assert workspace.load().highest_reveal_stage == 2
    assert len(workspace.history_records()) == 1
    assert [image.getpixel((160, 300)) for image in display.images] == [(127, 127, 127)] * 3
    for image in display.images:
        image.close()


def test_continuous_http_publication_progresses_while_another_backend_is_busy(workspace) -> None:
    ordinary(workspace)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    workspace.config.write_text(
        workspace.config.read_text(encoding="utf-8").replace(
            '    - type: "waveshare-13in3-e"',
            f'    - type: "window"\n    - type: "image-server"\n' f'      host: "127.0.0.1"\n      port: {port}',
        ),
        encoding="utf-8",
    )
    clock = RuntimeClock(at(10, 7))
    slow_started, release_slow, slow_updated, slow_closed = Event(), Event(), Event(), Event()
    slow_updates = []

    class SlowBackend:
        def update(self, image):
            slow_updates.append(image.copy())
            if len(slow_updates) == 1:
                slow_started.set()
                assert release_slow.wait(5)
            elif len(slow_updates) == 2:
                slow_updated.set()

        def close(self):
            slow_closed.set()

    def backend_factory(configuration):
        if configuration.type == "window":
            return SlowBackend()
        return create_display_backend(
            configuration.type,
            image_server_host=configuration.host,
            image_server_port=configuration.port,
        )

    def read_until(expected: bytes) -> None:
        deadline = monotonic() + 4
        while monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/display/current", timeout=0.25) as response:
                    if response.status == 200 and response.read() == expected:
                        return
            except OSError:
                pass
            sleep(0.02)
        pytest.fail("image-server did not publish the expected prepared stage")

    wait_count = 0

    def scheduling_wait(_deadline, _shutdown, **_kwargs):
        nonlocal wait_count
        wait_count += 1
        assert slow_started.wait(2)
        stage = wait_count - 1
        expected = next(workspace.artifacts.rglob(f"stage-{stage}.png")).read_bytes()
        read_until(expected)
        if wait_count == 1:
            clock.move(at(10, 12))
            return False
        assert not release_slow.is_set()
        release_slow.set()
        assert slow_updated.wait(2)
        clock.set()
        return True

    try:
        run_application(
            workspace.config,
            workspace.state,
            workspace.artifacts,
            shutdown_event=clock,
            random_source=Random(1),
            backend_factory=backend_factory,
            wall_clock=lambda: clock.now,
            monotonic_clock=lambda: clock.elapsed,
            scheduling_wait=scheduling_wait,
        )
    finally:
        release_slow.set()

    assert wait_count == 2
    assert workspace.load().highest_reveal_stage == 1
    assert len(slow_updates) == 2 and slow_closed.is_set()
    assert all(update.size == (1600, 1200) for update in slow_updates)


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a graphical display")
def test_window_and_image_server_publish_independently() -> None:
    pytest.importorskip("tkinter", reason="requires Tk support")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    configurations = (
        DisplayBackendConfiguration("window"),
        DisplayBackendConfiguration("image-server", host="127.0.0.1", port=port),
    )
    window = create_display_backend("window")
    window_update = window.update
    update_started, release_update = Event(), Event()

    def blocked_window_update(image):
        update_started.set()
        assert release_update.wait(5)
        window_update(image)

    window.update = blocked_window_update

    def backend_factory(configuration):
        if configuration.type == "window":
            return window
        return create_display_backend(
            configuration.type,
            image_server_host=configuration.host,
            image_server_port=configuration.port,
        )

    coordinator = DisplayPublicationCoordinator(configurations, backend_factory)
    expected = Image.new("RGB", (16, 12), (31, 47, 59))
    identity = (1, 0)
    try:
        coordinator.publish(identity, expected.copy())
        assert update_started.wait(2)
        deadline = monotonic() + 4
        while monotonic() < deadline:
            if coordinator.acknowledgements["image-server"] == identity:
                with urlopen(f"http://127.0.0.1:{port}/display/current", timeout=1) as response:
                    published = Image.open(BytesIO(response.read()))
                    assert published.size == expected.size
                    assert published.getpixel((0, 0)) == expected.getpixel((0, 0))
                break
            sleep(0.02)
        else:
            pytest.fail("image-server did not publish while the window update was blocked")
        release_update.set()
        assert coordinator.wait_for_publication(identity, timeout=2)
    finally:
        release_update.set()
        coordinator.close()


@pytest.mark.parametrize(
    ("extra", "events", "expected"),
    [
        ("", [at(10, 19)], [(1, 0), (1, 2)]),
        ('reveal:\n  source: "10:00"\n  attribution: "10:00"\n', [at(10, 10)], [(1, 0), (1, 1)]),
        ('reveal:\n  attribution: "09:00"\n', [at(10, 9), at(10, 12)], [(1, 0), (1, 1), (1, 2)]),
    ],
)
def test_continuous_missed_simultaneous_and_out_of_order_reveals(
    workspace, monkeypatch, extra, events, expected
) -> None:
    ordinary(workspace, extra=extra)
    stages, _, display = run_continuously(workspace, RuntimeClock(at(10, 7), events), monkeypatch)
    assert stages == expected and display.closed == 1
    assert workspace.load().highest_reveal_stage == expected[-1][1]


def test_continuous_daily_transitions_preserve_histories(workspace, monkeypatch) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n  - "Third."\n')
    clock = RuntimeClock(at(10, 7), [at(11, 6), at(11, 6), at(12, 6), at(13, 6)])
    stages, initialized, display = run_continuously(workspace, clock, monkeypatch)
    state = workspace.load()
    history = workspace.history_records()
    assert stages == [(1, 0), (2, 0), (3, 0), (4, 0)]
    assert state.revision == len(history) == 4
    assert [record["display_date"] for record in history] == [f"2026-03-{day:02}" for day in range(10, 14)]
    assert len({record["quotation_identity"] for record in history[:3]}) == 3
    assert state.repetition_history == {history[-1]["quotation_identity"]}
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1
    assert len(png_files(workspace.artifacts)) == 1


def test_continuous_restart_is_conservative_and_reuses_committed_snapshot(workspace, monkeypatch) -> None:
    ordinary(workspace)
    run_continuously(workspace, RuntimeClock(at(10, 7)), monkeypatch)
    first = workspace.load()
    artifacts = {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)}
    for path in workspace.content.iterdir():
        path.unlink()
    monkeypatch.setattr(application, "load_content_library", lambda *args: pytest.fail("content reloaded"))
    stages, initialized, display = run_continuously(workspace, RuntimeClock(at(14, 19)), monkeypatch)
    state = workspace.load()
    assert stages == [(1, 2)]
    assert state.snapshot == first.snapshot
    assert len(workspace.history_records()) == 1
    assert state.repetition_history == first.repetition_history and state.highest_reveal_stage == 2
    assert {path: path.stat().st_mtime_ns for path in png_files(workspace.artifacts)} == artifacts
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


def test_continuous_forward_jump_selects_only_current_date(workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 15\nquotations:\n  - "Special."\n')
    clock = RuntimeClock(at(10, 7), [at(15, 19)])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    state = workspace.load()
    assert stages == [(1, 0), (2, 0)]
    assert len(workspace.history_records()) == 2 and state.snapshot.display_date == date(2026, 3, 15)
    assert state.snapshot.quotation_text == "Special."


def test_continuous_backward_jump_preserves_reveal_until_new_boundary(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(15, 19), [at(12, 4), at(12, 5), at(12, 6)])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 2), (2, 0)]
    assert [record["display_date"] for record in workspace.history_records()] == ["2026-03-15", "2026-03-12"]


@pytest.mark.parametrize("published", [False, True])
def test_continuous_daily_commit_retry_and_uncertain_publication(workspace, monkeypatch, published) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit
    attempts = []

    def commit(self, proposal, snapshot):
        attempts.append(proposal.base_revision)
        if proposal.base_revision == 1 and attempts.count(1) == 1:
            if published:
                original(self, proposal, snapshot)
            raise StateCommitError("interrupted publication", published=published)
        return original(self, proposal, snapshot)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)]
    assert attempts == ([0, 1] if published else [0, 1, 1])
    assert len(workspace.history_records()) == 2
    assert clock.retry_delays == ([] if published else [1])


def test_continuous_later_boundary_supersedes_failed_transition(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit
    attempted_dates = []

    def commit(self, proposal, snapshot):
        attempted_dates.append(snapshot.display_date)
        if snapshot.display_date == date(2026, 3, 11):
            raise StateCommitError("disk full")
        return original(self, proposal, snapshot)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: clock.move(at(14, 7))])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)]
    assert attempted_dates == [date(2026, 3, day) for day in (10, 11, 14)]
    assert [record["display_date"][-2:] for record in workspace.history_records()] == ["10", "14"]


def test_continuous_pending_boundary_survives_backward_adjustment_during_retry(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.commit
    attempts = []

    def commit(self, proposal, snapshot):
        attempts.append(snapshot.display_date)
        if len(attempts) == 2:
            raise StateCommitError("disk full")
        return original(self, proposal, snapshot)

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: clock.move(at(9, 7))])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)]
    assert attempts == [date(2026, 3, day) for day in (10, 11, 11)]
    assert [record["display_date"][-2:] for record in workspace.history_records()] == ["10", "11"]


def test_continuous_preparation_failure_after_daily_commit_does_not_reselect(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = application.recover_prepared_daily_images
    attempts = []

    def recover(state, *args):
        attempts.append(state.revision)
        if state.revision == 2 and attempts.count(2) == 1:
            assert len(workspace.history_records()) == 2
            raise DailyImagePreparationError("temporary preparation failure")
        return original(state, *args)

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
    clock = RuntimeClock(at(10, 7), [at(11, 6)], retries=[lambda: clock.move(at(11, 19))])
    stages, initialized, display = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 2)]
    assert attempts == [1, 2, 2]
    assert len(workspace.history_records()) == 2
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_continuous_recovers_artifacts_damaged_between_reveals(workspace, monkeypatch, damage) -> None:
    ordinary(workspace)

    def damage_and_advance():
        for path in png_files(workspace.artifacts):
            if damage == "missing":
                path.unlink()
            else:
                path.write_bytes(b"damaged")
        clock.move(at(10, 12))

    clock = RuntimeClock(at(10, 7), [damage_and_advance], retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (1, 1)]
    assert clock.retry_delays == [1]
    assert workspace.load().revision == 1 and workspace.load().highest_reveal_stage == 1
    assert len(png_files(workspace.artifacts)) >= 3


def test_continuous_display_retry_without_event_or_reselection(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)
    clock = RuntimeClock(at(10, 7), retries=[lambda: setattr(display, "fail_update", False)])
    stages, initialized, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 0)] and clock.retry_delays == []
    assert workspace.load().revision == len(workspace.history_records()) == 1
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


def test_continuous_failed_display_skips_to_newer_desired_selection(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)

    clock = RuntimeClock(at(10, 7), [at(14, 19)])
    stages, initialized, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 0), (2, 2)]
    assert len(workspace.history_records()) == 2
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1


def test_continuous_reveal_persistence_retry_never_hides_successful_presentation(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PersistentStateStore.advance_reveal_progress
    attempts = []

    def advance(self, revision, stage):
        attempts.append(stage)
        if len(attempts) == 1:
            raise StateCommitError("disk full")
        return original(self, revision, stage)

    monkeypatch.setattr(PersistentStateStore, "advance_reveal_progress", advance)
    clock = RuntimeClock(at(10, 19), retries=[lambda: clock.move(at(10, 7))])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 2)] and attempts == [2, 2]
    assert workspace.load().highest_reveal_stage == 2


def test_continuous_initialization_retry(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    attempts = []

    def factory(configuration):
        attempts.append(configuration.type)
        if len(attempts) == 1:
            raise DisplayBackendInitializationError("temporarily unavailable")
        return display

    clock = RuntimeClock(at(10, 7), retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch, backend_factory=factory)
    assert stages == [(1, 0)] and len(attempts) == 1 and display.closed == 0
    assert workspace.load().revision == 1


@pytest.mark.parametrize("operation", ["initialize", "update"])
def test_continuous_terminal_display_error_stops_without_retry(workspace, monkeypatch, operation) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 7))
    display = FakeDisplay()
    update_failed = Event()

    def fail_update(image):
        update_failed.set()
        raise DisplayBackendUpdateError("backend disabled", recoverable=False)

    def initialize(configuration):
        if operation == "initialize":
            update_failed.set()
            raise DisplayBackendInitializationError("backend disabled", recoverable=False)
        return display

    display.update = fail_update

    def wait_for_terminal_failure(deadline, shutdown, **kwargs):
        assert update_failed.wait(1)
        return False

    with pytest.raises(ApplicationError, match="all configured display destinations"):
        run_continuously(
            workspace,
            clock,
            monkeypatch,
            backend_factory=initialize,
            scheduling_wait=wait_for_terminal_failure,
        )
    assert display.closed == (1 if operation == "update" else 0)
    assert clock.retry_delays == [] and clock.deadlines == []
    assert len(workspace.history_records()) == 1
    assert len(png_files(workspace.artifacts)) == 3


def test_continuous_shutdown_during_recovery_bounds_retries_and_logs(workspace, monkeypatch, caplog) -> None:
    ordinary(workspace)
    update_failed = Event()

    class FailingDisplay(FakeDisplay):
        def update(self, image):
            update_failed.set()
            super().update(image)

    display = FailingDisplay(fail_update=True)
    clock = RuntimeClock(at(10, 7), retries=[lambda: None] * 8)

    def shutdown_after_failure(_deadline, shutdown, **_kwargs):
        assert update_failed.wait(1)
        shutdown.set()
        return True

    with caplog.at_level(logging.WARNING):
        stages, _, _ = run_continuously(
            workspace,
            clock,
            monkeypatch,
            display,
            scheduling_wait=shutdown_after_failure,
        )
    assert stages == [(1, 0)] and display.closed == 1
    assert clock.retry_delays == []
    assert caplog.text.count("Display backend waveshare-13in3-e update failed") == 1
    assert workspace.load().revision == 1 and png_files(workspace.artifacts)


def test_continuous_content_failure_preserves_previous_state_for_retry(workspace, monkeypatch) -> None:
    ordinary(workspace)
    path = workspace.content / "ordinary.yaml"
    original = path.read_text(encoding="utf-8")
    previous = []
    previous_artifacts = []

    def remove_content():
        previous.append(workspace.load())
        previous_artifacts.append(tuple(item.read_bytes() for item in png_files(workspace.artifacts)))
        path.unlink()
        clock.move(at(11, 6))

    def restore_content():
        assert workspace.load() == previous[0]
        assert tuple(item.read_bytes() for item in png_files(workspace.artifacts)) == previous_artifacts[0]
        path.write_text(original, encoding="utf-8")

    clock = RuntimeClock(at(10, 7), [remove_content], retries=[restore_content])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0), (2, 0)] and clock.retry_delays == [1]
    assert len(workspace.history_records()) == 2


def test_partial_library_selects_at_daily_boundary_and_logs_rejection_once(workspace, monkeypatch, caplog) -> None:
    workspace.entry("many", 'quotations:\n  - "First."\n  - "Second."\n')
    rejected = workspace.content / "invalid.yaml"
    rejected.write_text("id: invalid id\nquotations: [Rejected.]\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        stages, _, _ = run_continuously(
            workspace,
            RuntimeClock(at(10, 7), [at(11, 6), at(12, 6)]),
            monkeypatch,
        )

    assert stages == [(1, 0), (2, 0), (3, 0)]
    assert workspace.load().revision == len(workspace.history_records()) == 3
    assert caplog.text.count(str(rejected)) == 1


def test_continuous_retry_does_not_repeat_unchanged_content_warnings(workspace, monkeypatch, caplog) -> None:
    workspace.entry("seasonal", 'eligibility:\n  - month: 7\nquotations:\n  - "Summer."\n')
    rejected = workspace.content / "invalid.yaml"
    rejected.write_text("id: invalid id\nquotations: [Rejected.]\n", encoding="utf-8")

    def add_eligible_content():
        ordinary(workspace, "Recovered quotation.")

    clock = RuntimeClock(at(10, 7), retries=[add_eligible_content])
    with caplog.at_level(logging.WARNING):
        stages, _, _ = run_continuously(workspace, clock, monkeypatch)

    assert stages == [(1, 0)]
    assert clock.retry_delays == [1]
    assert caplog.text.count(str(rejected)) == 1


@pytest.mark.parametrize("failure", ["configuration", "state"])
def test_continuous_unrecoverable_errors_terminate_without_retry(workspace, monkeypatch, failure) -> None:
    ordinary(workspace)
    if failure == "configuration":
        workspace.config.write_text("invalid: true", encoding="utf-8")
    else:
        workspace.state.parent.mkdir()
        workspace.state.write_text("corrupt", encoding="utf-8")
    clock = RuntimeClock(at(10, 7))
    with pytest.raises(ApplicationError, match="configuration|persistent state"):
        run_continuously(workspace, clock, monkeypatch)
    assert clock.retry_delays == [] and clock.deadlines == []


def test_continuous_uncertain_publication_with_temporary_reload_failure(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original_commit = PersistentStateStore.commit
    original_load = PersistentStateStore.load
    unreadable = False

    def commit(self, *args):
        nonlocal unreadable
        original_commit(self, *args)
        unreadable = True
        raise StateCommitError("durability unconfirmed", published=True)

    def load(self):
        if unreadable:
            raise StateRecoveryError("temporary read failure") from OSError("temporarily unavailable")
        return original_load(self)

    def recover_storage():
        nonlocal unreadable
        unreadable = False

    monkeypatch.setattr(PersistentStateStore, "commit", commit)
    monkeypatch.setattr(PersistentStateStore, "load", load)
    clock = RuntimeClock(at(10, 7), retries=[recover_storage])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0)] and clock.retry_delays == [1]
    assert len(workspace.history_records()) == 1


def test_continuous_uncertain_artifact_publication_reloads_without_regeneration(workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = PreparedImageArtifactStore.store
    publications = []

    def publish(self, revision, snapshot, images):
        publications.append(revision)
        original(self, revision, snapshot, images)
        raise ArtifactWriteError("directory sync unconfirmed", published=True)

    monkeypatch.setattr(PreparedImageArtifactStore, "store", publish)
    clock = RuntimeClock(at(10, 7), retries=[lambda: None])
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 0)] and publications == [1]
    assert clock.retry_delays == [1]
    assert len(workspace.history_records()) == 1


def test_backend_retry_does_not_block_scheduler_or_shutdown(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay(fail_update=True)
    clock = RuntimeClock(at(10, 7))
    delays = []

    def wait(timeout):
        delays.append(timeout)
        if len(delays) == 1:
            clock.elapsed += 0.25
            clock.now = at(9, 7)
        else:
            clock.elapsed += timeout
            display.fail_update = False
        return False

    clock.wait = wait
    stages, _, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert delays == [] and stages == [(1, 0)]
    assert workspace.load().revision == 1


def test_continuous_real_scheduling_wait_is_interrupted_by_shutdown(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 7))
    clock.scheduling_wait = application.wait_for_scheduling_event
    _, _, display = run_continuously(workspace, clock, monkeypatch)
    assert clock.is_set() and display.closed == 1
    assert clock.retry_delays == [300]


def test_continuous_shutdown_during_update_persists_successful_reveal(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 19))
    display = FakeDisplay()
    original = display.update

    def update(image):
        original(image)
        clock.set()

    display.update = update
    stages, _, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 2)] and display.closed == 1
    assert workspace.load().highest_reveal_stage == 2


def test_continuous_slow_preparation_rechecks_latest_stage_before_presenting(workspace, monkeypatch) -> None:
    ordinary(workspace)
    clock = RuntimeClock(at(10, 7))
    original = application.recover_prepared_daily_images

    def recover(*args):
        images = original(*args)
        clock.move(at(10, 19))
        return images

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
    stages, _, _ = run_continuously(workspace, clock, monkeypatch)
    assert stages == [(1, 2)] and workspace.load().highest_reveal_stage == 2


def test_continuous_daily_display_failure_retains_commit_and_prepared_images(workspace, monkeypatch) -> None:
    ordinary(workspace)
    display = FakeDisplay()
    prepared = []
    original = application.recover_prepared_daily_images

    def recover(state, *args):
        prepared.append(state.revision)
        return original(state, *args)

    def fail_daily_update():
        display.fail_update = True
        clock.move(at(11, 6))

    def restore_display():
        state = workspace.load()
        assert state.revision == len(workspace.history_records()) == 2
        assert len(png_files(workspace.artifacts)) == 3
        display.fail_update = False

    monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
    clock = RuntimeClock(at(10, 7), [fail_daily_update], retries=[restore_display])
    stages, initialized, _ = run_continuously(workspace, clock, monkeypatch, display)
    assert stages == [(1, 0), (2, 0)] and prepared == [1, 2]
    assert initialized == ["waveshare-13in3-e"] and display.closed == 1
    assert len(workspace.history_records()) == 2


def test_command_line_defaults_to_continuous_and_restores_signal_handlers(workspace, monkeypatch) -> None:
    import signal

    import refrain.__main__ as command_line

    calls = []
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def run(config, state, artifacts, *, shutdown_event, **kwargs):
        calls.append((config, state, artifacts))
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert shutdown_event.is_set()

    monkeypatch.setattr(command_line, "run_application", run)
    assert (
        main(
            [
                "--config",
                str(workspace.config),
                "--state",
                str(workspace.state),
                "--artifacts",
                str(workspace.artifacts),
            ]
        )
        == 0
    )
    assert calls == [(str(workspace.config), str(workspace.state), str(workspace.artifacts))]
    assert {sig: signal.getsignal(sig) for sig in handlers} == handlers

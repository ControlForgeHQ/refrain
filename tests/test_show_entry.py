from __future__ import annotations

from pathlib import Path
from random import Random
from types import SimpleNamespace

import pytest
from PIL import Image

import refrain.__main__ as cli
import refrain.application as application
from refrain import ApplicationError
from refrain.display import DisplayBackendInitializationError
from refrain.geometry import (
    DEFAULT_PRESENTATION_INSETS,
    PresentationInsets,
    ResolvedOutputSpecification,
    resolve_presentation_geometry,
)
from refrain.qr import PRODUCTION_QR_PARAMETERS, render_qr_code, resolve_qr_placement

_CONFIG = """\
general:
  day_start: "06:00"
content:
  directory: content
reveal:
  source: "12:00"
  attribution: "18:00"
display:
  backends:
    - type: "window"
information_view:
  duration: 0
layout:
  presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}
  fonts:
    default: ["lora"]
  text: {min_font_size: 28, max_font_size: 100}
"""


def assert_default_literary_bounds(image: Image.Image) -> None:
    bounds = resolve_presentation_geometry(
        ResolvedOutputSpecification("16:9", (1920, 1080)),
        PresentationInsets(*DEFAULT_PRESENTATION_INSETS),
    ).presentation_literary_bounds
    assert image.getpixel((bounds[0], bounds[1])) == (127, 127, 127)


def assert_production_qr_geometry(image: Image.Image) -> None:
    specification = ResolvedOutputSpecification("16:9", image.size)
    qr = render_qr_code(PRODUCTION_QR_PARAMETERS, image.size, resolve_qr_placement(specification))
    try:
        left, top, _, _ = qr.geometry.bounds
        quiet_zone = qr.geometry.quiet_zone_pixels
        assert image.getpixel((left, top)) == (255, 255, 255)
        assert image.getpixel((left + quiet_zone, top + quiet_zone)) == (0, 0, 0)
    finally:
        qr.image.close()


class RecordingBackend:
    def __init__(self) -> None:
        self.images: list[Image.Image] = []
        self.closed = False

    def update(self, image: Image.Image) -> None:
        self.images.append(image.copy())

    def update_output(self, _output_id: str, image: Image.Image) -> None:
        self.update(image)

    def close(self) -> None:
        self.closed = True


def workspace(root: Path) -> tuple[Path, Path]:
    config = root / "configuration" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(_CONFIG, encoding="utf-8")
    content = config.parent / "content"
    content.mkdir()
    return config, content


def test_show_entry_selects_first_quote_and_publishes_fully_revealed_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, content = workspace(tmp_path)
    (content / "filename-does-not-match.yaml").write_text(
        """\
id: "requested-entry"
priority: 100
eligibility:
  - year: 2000
    month: 1
    day: 1
source: "A source"
attribution: "An author"
quotations:
  - "First quotation."
  - "Second quotation."
""",
        encoding="utf-8",
    )
    output_directory = tmp_path / "working-directory"
    output_directory.mkdir()
    monkeypatch.chdir(output_directory)

    backend = RecordingBackend()
    captured: dict[str, object] = {}
    prepare = application.prepare_daily_images

    def capture_preparation(snapshot, stages, configuration, output_specifications, **kwargs):
        captured["snapshot"] = snapshot
        captured["stages"] = stages
        return prepare(snapshot, stages, configuration, output_specifications, **kwargs)

    def unexpected_selection(*_args, **_kwargs):
        pytest.fail("diagnostic selection must not use the ordinary candidate pool")

    monkeypatch.setattr(application, "prepare_daily_images", capture_preparation)
    monkeypatch.setattr(application, "select_quotation", unexpected_selection)
    monkeypatch.setattr(application, "build_eligible_quotation_pool", unexpected_selection)

    output = application.run_show_entry(
        config,
        "requested-entry",
        debug_layout=True,
        random_source=Random(1),
        backend_factory=lambda _: backend,
    )

    snapshot = captured["snapshot"]
    assert snapshot.quotation_text == "First quotation."
    assert snapshot.source == "A source"
    assert snapshot.attribution == "An author"
    assert captured["stages"][-1].source
    assert captured["stages"][-1].attribution
    assert output is None
    assert list(output_directory.iterdir()) == []
    assert len(backend.images) == 1
    assert backend.images[0].mode == "RGB"
    assert backend.images[0].size == (1920, 1080)
    assert_default_literary_bounds(backend.images[0])
    assert_production_qr_geometry(backend.images[0])
    assert backend.closed
    for image in backend.images:
        image.close()


def test_show_entry_does_not_initialize_backends_or_create_png_when_entry_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, content = workspace(tmp_path)
    (content / "another-entry.yaml").write_text(
        'id: another-entry\nquotations: ["An unrelated quotation."]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    initialized = []

    def factory(configuration):
        initialized.append(configuration.type)
        pytest.fail("a missing entry must be rejected before backend initialization")

    with pytest.raises(ApplicationError, match="requested-entry.*not found"):
        application.run_show_entry(config, "requested-entry", backend_factory=factory)
    assert initialized == []
    assert not (tmp_path / "refrain-requested-entry.png").exists()


def test_cli_returns_nonzero_for_a_missing_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, content = workspace(tmp_path)
    (content / "another-entry.yaml").write_text(
        'id: another-entry\nquotations: ["An unrelated quotation."]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["--show-entry", "missing-entry", "--config", str(config)]) == 1
    assert "missing-entry" in capsys.readouterr().err
    assert not (tmp_path / "refrain-missing-entry.png").exists()


def test_existing_refrain_png_is_not_part_of_show_entry_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, content = workspace(tmp_path)
    (content / "entry.yaml").write_text('id: entry\nquotations: ["A quotation."]\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "refrain-entry.png"
    output.write_bytes(b"existing file")
    backend = RecordingBackend()

    assert application.run_show_entry(config, "entry", backend_factory=lambda _: backend) is None
    assert output.read_bytes() == b"existing file"
    assert len(backend.images) == 1
    assert backend.closed
    for image in backend.images:
        image.close()


def test_show_entry_does_not_save_a_diagnostic_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, content = workspace(tmp_path)
    (content / "entry.yaml").write_text('id: entry\nquotations: ["A quotation."]\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    backend = RecordingBackend()
    assert application.run_show_entry(config, "entry", backend_factory=lambda _: backend) is None
    assert not (tmp_path / "refrain-entry.png").exists()
    assert len(backend.images) == 1
    assert backend.closed
    for image in backend.images:
        image.close()


def test_information_target_uses_existing_renderer_without_loading_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, content = workspace(tmp_path)
    content.rmdir()
    monkeypatch.chdir(tmp_path)
    backend = RecordingBackend()
    prepared = []
    prepare = application.prepare_information_view

    def capture_information(configuration, output_specifications):
        prepared.append(configuration)
        return prepare(configuration, output_specifications)

    def unexpected_content_load(_directory):
        pytest.fail("the reserved information target must not load the content library")

    monkeypatch.setattr(application, "prepare_information_view", capture_information)
    monkeypatch.setattr(application, "load_content_library", unexpected_content_load)
    output = application.run_show_entry(config, "information", debug_layout=True, backend_factory=lambda _: backend)

    assert prepared and prepared[0].information_view_duration == 0
    assert output is None
    assert len(backend.images) == 1
    assert backend.images[0].mode == "RGB"
    assert backend.images[0].size == (1920, 1080)
    assert backend.images[0].getpixel((1437, 1037)) == (250, 249, 245)
    assert backend.closed
    for image in backend.images:
        image.close()


def test_information_target_takes_precedence_over_a_content_entry_with_the_same_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, content = workspace(tmp_path)
    (content / "information.yaml").write_text(
        'id: information\nquotations: ["This entry must not be presented."]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr(
        application,
        "prepare_information_view",
        lambda configuration, output_specifications: {output_specifications[0]: (Image.new("RGB", (4, 4), (7, 8, 9)),)},
    )
    monkeypatch.setattr(
        application,
        "load_content_library",
        lambda _directory: pytest.fail("the reserved target must bypass content-entry lookup"),
    )

    output = application.run_show_entry(config, "information", debug_layout=True, backend_factory=lambda _: backend)

    assert output is None
    assert len(backend.images) == 1
    assert backend.images[0].getpixel((0, 0)) == (7, 8, 9)
    assert backend.closed
    for image in backend.images:
        image.close()


def test_every_configured_backend_receives_the_same_diagnostic_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, content = workspace(tmp_path)
    config.write_text(
        _CONFIG.replace(
            '    - type: "window"',
            '    - type: "window"\n    - type: "image-server"\n'
            '      outputs:\n        - id: "default"\n'
            '          aspect_ratio: "4:3"\n          resolution: [1600, 1200]',
        ),
        encoding="utf-8",
    )
    (content / "entry.yaml").write_text('id: entry\nquotations: ["A quotation."]\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    backends = {"window": RecordingBackend(), "image-server": RecordingBackend()}

    output = application.run_show_entry(
        config,
        "entry",
        debug_layout=True,
        backend_factory=lambda configuration: backends[configuration.type],
    )

    assert output is None
    assert all(len(backend.images) == 1 and backend.closed for backend in backends.values())
    assert backends["window"].images[0].size == (1920, 1080)
    assert backends["image-server"].images[0].size == (1600, 1200)
    assert backends["window"].images[0].tobytes() != backends["image-server"].images[0].tobytes()
    assert_default_literary_bounds(backends["window"].images[0])
    assert_production_qr_geometry(backends["window"].images[0])
    for backend in backends.values():
        for image in backend.images:
            image.close()


def test_partial_publication_failure_isolated_and_closes_backends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config, content = workspace(tmp_path)
    config.write_text(
        _CONFIG.replace(
            '    - type: "window"',
            '    - type: "window"\n    - type: "image-server"\n' '      outputs:\n        - id: "default"',
        ),
        encoding="utf-8",
    )
    (content / "entry.yaml").write_text('id: entry\nquotations: ["A quotation."]\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    healthy = RecordingBackend()
    initialized: list[str] = []

    def factory(configuration):
        initialized.append(configuration.type)
        if configuration.type == "image-server":
            raise DisplayBackendInitializationError("server unavailable", recoverable=False)
        return healthy

    original = application.run_show_entry
    monkeypatch.setattr(
        cli,
        "run_show_entry",
        lambda config_path, entry_id, **kwargs: original(
            config_path, entry_id, debug_layout=kwargs["debug_layout"], backend_factory=factory
        ),
    )
    assert cli.main(["--show-entry", "entry", "--config", str(config)]) == 1

    assert set(initialized) == {"window", "image-server"}
    assert healthy.closed
    assert not (tmp_path / "refrain-entry.png").exists()
    assert "image-server" in caplog.text
    assert "not published by every" in capsys.readouterr().err
    for image in healthy.images:
        image.close()


@pytest.mark.parametrize(
    "mode",
    [
        ["--once"],
        ["--demo", "1"],
        ["--initialize"],
        ["--reset"],
        ["--purge"],
    ],
)
def test_show_entry_is_mutually_exclusive_with_other_modes(mode: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--show-entry", "entry", *mode])


@pytest.mark.parametrize("arguments", [["--show-entry"], ["--show-entry", ""], ["--show-entry", "../entry"]])
def test_show_entry_requires_a_valid_identifier(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(arguments)


def test_cli_ignores_production_persistence_overrides_and_uses_configured_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, content = workspace(tmp_path / "selected")
    (content / "entry.yaml").write_text('id: entry\nquotations: ["A quotation."]\n', encoding="utf-8")
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    state = tmp_path / "production-state.json"
    history = tmp_path / "production-history.jsonl"
    artifacts = tmp_path / "production-artifacts"
    state.write_bytes(b"unchanged state")
    history.write_bytes(b"unchanged history")
    artifacts.mkdir()
    (artifacts / "production.png").write_bytes(b"unchanged artifact")
    backend = RecordingBackend()
    original = application.run_show_entry

    def run_with_backend(config_path, entry_id, **kwargs):
        return original(
            config_path,
            entry_id,
            debug_layout=kwargs["debug_layout"],
            backend_factory=lambda _: backend,
        )

    monkeypatch.setattr(cli, "run_show_entry", run_with_backend)
    assert (
        cli.main(
            [
                "--show-entry",
                "entry",
                "--debug-layout",
                "--config",
                str(config),
                "--state",
                str(state),
                "--history",
                str(history),
                "--artifacts",
                str(artifacts),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == ""
    assert not (working_directory / "refrain-entry.png").exists()
    assert state.read_bytes() == b"unchanged state"
    assert history.read_bytes() == b"unchanged history"
    assert (artifacts / "production.png").read_bytes() == b"unchanged artifact"
    assert_default_literary_bounds(backend.images[0])
    assert backend.closed
    for image in backend.images:
        image.close()


def test_cli_uses_default_configuration_path_for_show_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "default-config.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    observed = []
    monkeypatch.setattr(
        cli,
        "resolve_application_paths",
        lambda: SimpleNamespace(config_file=config, state_file=tmp_path / "unused-state"),
    )
    monkeypatch.setattr(
        cli,
        "run_show_entry",
        lambda path, entry_id, **kwargs: observed.append((path, entry_id, kwargs)),
    )

    assert cli.main(["--show-entry", "entry", "--debug-layout"]) == 0
    assert observed == [(config, "entry", {"debug_layout": True})]

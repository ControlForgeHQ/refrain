from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import refrain.application as application
import refrain.display
import refrain.preparation as preparation
import refrain.viewer as viewer
from refrain.config import load_application_config
from refrain.preparation import PresentationOverrides, prepare_daily_images
from refrain.presentation import build_presentation_snapshot
from refrain.scheduling import resolve_reveal_stages

_CONFIG = """\
general:
  day_start: "06:00"
content:
  directory: content
display:
  backends:
    - type: image-server
      outputs:
        - id: configured-output
information_view:
  duration: 0
layout:
  presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}
  fonts:
    default: ["lora"]
  text: {min_font_size: 28, max_font_size: 100}
storage:
  state: state.json
  history: history.jsonl
  artifacts: artifacts
"""

_ENTRY = """\
id: requested-entry
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
"""


def _workspace(root: Path, *, with_entry: bool = True) -> tuple[Path, Path]:
    config = root / "config.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    content = root / "content"
    content.mkdir()
    if with_entry:
        (content / "entry.yaml").write_text(_ENTRY, encoding="utf-8")
    return config, content


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("johnson-maggie", ("johnson-maggie", 1)),
        ("johnson-maggie:1", ("johnson-maggie", 1)),
        ("johnson-maggie:6", ("johnson-maggie", 6)),
        ("@preview", ("@preview", 1)),
        ("@preview:2", ("@preview", 2)),
    ],
)
def test_entry_selector_supports_exact_ids_and_one_based_indexes(selector: str, expected: tuple[str, int]) -> None:
    assert viewer.parse_entry_selector(selector) == expected


@pytest.mark.parametrize("selector", ["", ":1", "entry:", "entry:0", "entry:-1", "entry:1.0", "entry:abc", "entry:1:2"])
def test_entry_selector_rejects_malformed_or_nonpositive_indexes(selector: str) -> None:
    with pytest.raises(viewer.argparse.ArgumentTypeError):
        viewer.parse_entry_selector(selector)


@pytest.mark.parametrize(
    ("aspect", "size"),
    [
        ("4:3", (3200, 2400)),
        ("5:3", (3840, 2304)),
        ("16:9", (3840, 2160)),
        ("16:10", (3840, 2400)),
    ],
)
def test_viewer_default_output_uses_full_design_canvas(aspect: str, size: tuple[int, int]) -> None:
    specification = viewer._output_specification(aspect, None)

    assert specification.requested_output_size == size
    assert specification.presentation_canvas_size == size


def test_viewer_resolution_preserves_declared_aspect_and_output_size() -> None:
    specification = viewer._output_specification("4:3", (1600, 1190))

    assert specification.aspect_ratio == "4:3"
    assert specification.presentation_canvas_size == (1596, 1197)
    assert specification.requested_output_size == (1600, 1190)


def test_default_entry_selects_medium_preview_and_explicit_selector_matches(tmp_path: Path) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    default_arguments = viewer._parser().parse_args([])

    default_entry, default_quote = viewer._select_entry(configuration, default_arguments.entry)
    explicit_entry, explicit_quote = viewer._select_entry(configuration, ("@preview", 2))

    assert default_arguments.entry == ("@preview", 2)
    assert default_entry.id == explicit_entry.id == "@preview"
    assert default_quote == explicit_quote
    assert default_quote.text != viewer._PREVIEW_ENTRY.quotations[0].text
    assert len(viewer._PREVIEW_ENTRY.quotations) >= 3
    assert default_entry.source
    assert default_entry.attribution


def test_normal_entry_selection_ignores_eligibility_priority_and_selects_requested_quote(tmp_path: Path) -> None:
    config_path, _ = _workspace(tmp_path)
    configuration = load_application_config(config_path)

    entry, quotation = viewer._select_entry(configuration, ("requested-entry", 2))
    omitted_entry, first_quotation = viewer._select_entry(configuration, ("requested-entry", 1))

    assert entry.id == omitted_entry.id == "requested-entry"
    assert quotation.text == "Second quotation."
    assert first_quotation.text == "First quotation."
    assert entry.priority == 100
    assert entry.eligibility[0].year == 2000


def test_entry_selection_rejects_missing_entry_and_out_of_range_quote(tmp_path: Path) -> None:
    config_path, _ = _workspace(tmp_path)
    configuration = load_application_config(config_path)

    with pytest.raises(viewer.ViewerError, match="not found"):
        viewer._select_entry(configuration, ("missing-entry", 1))
    with pytest.raises(viewer.ViewerError, match="out of range"):
        viewer._select_entry(configuration, ("requested-entry", 3))


def test_png_export_uses_shared_presentation_without_persistence_or_backend_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = _workspace(tmp_path)
    sentinels = {
        tmp_path / "state.json": b"state sentinel",
        tmp_path / "history.jsonl": b"history sentinel",
        tmp_path / "artifacts": b"artifact sentinel",
    }
    for path, content in sentinels.items():
        path.write_bytes(content)
    output = tmp_path / "entry.png"
    captured: dict[str, object] = {}
    prepare = viewer.prepare_daily_images

    def capture_preparation(snapshot, stages, configuration, specifications, **kwargs):
        captured["snapshot"] = snapshot
        captured["stages"] = stages
        captured["specifications"] = specifications
        return prepare(snapshot, stages, configuration, specifications, **kwargs)

    def unexpected_backend(*_args, **_kwargs):
        pytest.fail("the viewer must not initialize a configured display backend")

    monkeypatch.setattr(viewer, "prepare_daily_images", capture_preparation)
    monkeypatch.setattr(refrain.display, "create_display_backend", unexpected_backend)

    assert (
        viewer.main(
            [
                "--config",
                str(config),
                "--entry",
                "requested-entry:2",
                "--resolution",
                "320",
                "200",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (320, 200)
    assert captured["snapshot"].quotation_text == "Second quotation."
    assert captured["stages"][-1].source is True
    assert captured["stages"][-1].attribution is True
    assert captured["specifications"][0].aspect_ratio == "16:10"
    assert {path: path.read_bytes() for path in sentinels} == sentinels


@pytest.mark.parametrize(
    ("extra_arguments", "expected_window", "expected_output"),
    [
        ([], True, False),
        (["--output"], False, True),
        (["--window"], True, False),
        (["--output", "--window"], True, True),
    ],
)
def test_output_flags_select_window_and_png_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_arguments: list[str],
    expected_window: bool,
    expected_output: bool,
) -> None:
    config, _ = _workspace(tmp_path, with_entry=False)
    output = tmp_path / "preview.png"
    output_arguments = ["--output", str(output)] if "--output" in extra_arguments else []
    arguments = ["--config", str(config), "--resolution", "320", "200"]
    arguments.extend(output_arguments)
    arguments.extend(argument for argument in extra_arguments if argument != "--output")
    rendered = Image.new("RGB", (320, 200), (10, 20, 30))
    windows: list[tuple[int, int]] = []

    monkeypatch.setattr(viewer, "render_preview", lambda *_args, **_kwargs: rendered.copy())
    monkeypatch.setattr(viewer, "show_preview_window", lambda image: windows.append(image.size))

    assert viewer.main(arguments) == 0
    assert bool(windows) is expected_window
    assert output.exists() is expected_output
    if expected_output:
        assert output.stat().st_size > 0
    rendered.close()


def test_desktop_fit_scales_a_copy_without_changing_the_output_image() -> None:
    output = Image.new("RGB", (320, 200), (10, 20, 30))

    desktop = viewer._fit_preview_image(output, (100, 100))

    assert desktop.size == (100, 62)
    assert output.size == (320, 200)
    assert output.getpixel((0, 0)) == (10, 20, 30)
    desktop.close()
    output.close()


def test_png_write_failure_returns_actionable_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = _workspace(tmp_path, with_entry=False)
    output_directory = tmp_path / "output-directory"
    output_directory.mkdir()
    monkeypatch.setattr(viewer, "render_preview", lambda *_args, **_kwargs: Image.new("RGB", (320, 200)))

    assert viewer.main(["--config", str(config), "--output", str(output_directory)]) == 1
    assert "cannot write PNG output" in capsys.readouterr().err


def test_unavailable_window_returns_actionable_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = _workspace(tmp_path, with_entry=False)
    monkeypatch.setattr(viewer, "render_preview", lambda *_args, **_kwargs: Image.new("RGB", (320, 200)))

    def unavailable(_image):
        raise viewer.ViewerError("window display is unavailable; start a graphical desktop session")

    monkeypatch.setattr(viewer, "show_preview_window", unavailable)

    assert viewer.main(["--config", str(config)]) == 1
    assert "window display is unavailable" in capsys.readouterr().err


def test_missing_configuration_returns_actionable_cli_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert viewer.main(["--config", str(tmp_path / "missing.yaml"), "--output", str(tmp_path / "out.png")]) == 1
    assert "configuration file does not exist" in capsys.readouterr().err


def test_invalid_configuration_returns_nonzero_cli_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "invalid.yaml"
    config.write_text("not: [valid", encoding="utf-8")

    assert viewer.main(["--config", str(config), "--output", str(tmp_path / "out.png")]) == 1
    assert "configuration is invalid" in capsys.readouterr().err


def test_viewer_passes_typed_overrides_to_shared_preparation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config)
    overrides = PresentationOverrides(font="lora", style="left-aligned", qr_enabled=False)
    captured: dict[str, object] = {}

    def capture_preparation(_snapshot, _stages, _configuration, specifications, **kwargs):
        captured.update(kwargs)
        return {specifications[0]: (Image.new("RGB", (10, 10)),)}

    monkeypatch.setattr(viewer, "prepare_daily_images", capture_preparation)

    image = viewer.render_preview(
        configuration,
        ("@preview", 2),
        viewer._output_specification("16:10", (320, 200)),
        overrides=overrides,
    )
    try:
        assert captured["overrides"] == overrides
        assert captured["on_presentation_image"] is None
    finally:
        image.close()


def test_debug_layout_uses_shared_literary_qr_and_nine_slice_overlays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    specification = viewer._output_specification("16:10", (160, 100))
    diagnostics = SimpleNamespace(
        geometry=SimpleNamespace(
            presentation_literary_bounds=(10, 10, 150, 90),
            design_canvas_size=(160, 100),
        ),
        qr_placement=SimpleNamespace(presentation_allocation_bounds=(100, 60, 120, 80)),
        nine_slice_guides=(SimpleNamespace(layer_index=1, x_bounds=(0, 30, 130, 160), y_bounds=(0, 40, 60, 100)),),
    )

    def prepare(_snapshot, _stages, _configuration, specifications, **kwargs):
        image = Image.new("RGB", (160, 100), "white")
        kwargs["on_presentation_image"](specifications[0], image, diagnostics)
        return {specifications[0]: (image,)}

    monkeypatch.setattr(viewer, "prepare_daily_images", prepare)

    image = viewer.render_preview(configuration, ("@preview", 2), specification, debug_layout=True)
    try:
        assert image.getpixel((10, 50)) == (127, 127, 127)
        assert image.getpixel((100, 65)) == (255, 0, 255)
        assert image.getpixel((30, 50)) == (255, 25, 25)
    finally:
        image.close()


def test_runtime_and_viewer_share_presentation_construction_and_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    entry, quotation = viewer._select_entry(configuration, ("@preview", 2))
    runtime_snapshot = application._build_snapshot(configuration, entry, quotation, date.today())
    viewer_snapshot = build_presentation_snapshot(configuration, entry, quotation, date.today())
    resolutions = []
    resolve_choices = preparation._resolve_presentation_choices

    def capture_resolution(*args, **kwargs):
        resolutions.append(kwargs["overrides"])
        return resolve_choices(*args, **kwargs)

    monkeypatch.setattr(preparation, "_resolve_presentation_choices", capture_resolution)
    specification = viewer._output_specification("16:10", (320, 200))
    runtime_images = prepare_daily_images(
        runtime_snapshot,
        resolve_reveal_stages(runtime_snapshot)[-1:],
        configuration,
        (specification,),
    )
    try:
        viewer_image = viewer.render_preview(
            configuration,
            ("@preview", 2),
            specification,
            overrides=PresentationOverrides(style="left-aligned"),
        )
        viewer_image.close()
    finally:
        for images in runtime_images.values():
            for image in images:
                image.close()

    assert runtime_snapshot == viewer_snapshot
    assert len(resolutions) == 2
    assert resolutions[0] == PresentationOverrides()
    assert resolutions[1] == PresentationOverrides(style="left-aligned")

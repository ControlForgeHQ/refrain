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
from refrain.config import ApplicationConfiguration, load_application_config
from refrain.geometry import ResolvedOutputSpecification
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


def _capture_rendered_bounds(
    monkeypatch: pytest.MonkeyPatch,
    configuration: ApplicationConfiguration,
    selector: tuple[str, int],
    specification: ResolvedOutputSpecification,
    overrides: PresentationOverrides | None = None,
) -> tuple[int, int]:
    bounds: list[tuple[int, int]] = []
    layout = preparation.layout_composition

    def capture(*args, **kwargs):
        bounds.append((args[4], args[5]))
        return layout(*args, **kwargs)

    monkeypatch.setattr(preparation, "layout_composition", capture)
    image = viewer.render_preview(configuration, selector, specification, overrides=overrides)
    image.close()
    assert len(bounds) == 1
    return bounds[0]


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
    ("option", "expected"),
    [
        ("--min-font-size", 48),
        ("--max-font-size", 120),
    ],
)
def test_font_size_options_accept_positive_integers(option: str, expected: int) -> None:
    arguments = viewer._parser().parse_args([option, str(expected)])

    assert getattr(arguments, option[2:].replace("-", "_")) == expected


def test_font_size_options_can_be_supplied_together() -> None:
    arguments = viewer._parser().parse_args(["--min-font-size", "48", "--max-font-size", "120"])

    assert arguments.min_font_size == 48
    assert arguments.max_font_size == 120


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--min-font-size", "0"),
        ("--min-font-size", "-1"),
        ("--min-font-size", "1.5"),
        ("--min-font-size", "nope"),
        ("--max-font-size", "0"),
        ("--max-font-size", "-1"),
        ("--max-font-size", "1.5"),
        ("--max-font-size", "nope"),
    ],
)
def test_font_size_options_reject_nonpositive_or_noninteger_values(option: str, value: str) -> None:
    with pytest.raises(SystemExit):
        viewer._parser().parse_args([option, value])


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

    default_entry, default_quote = viewer._select_entry(
        configuration, default_arguments.entry or viewer._DEFAULT_SELECTOR
    )
    explicit_entry, explicit_quote = viewer._select_entry(configuration, ("@preview", 2))

    assert default_arguments.entry is None
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
                "--min-font-size",
                "36",
                "--max-font-size",
                "90",
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


def test_main_builds_font_size_overrides_from_cli_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(viewer, "run_viewer", lambda **kwargs: captured.update(kwargs))

    assert viewer.main(["--min-font-size", "48", "--max-font-size", "120"]) == 0

    overrides = captured["overrides"]
    assert isinstance(overrides, PresentationOverrides)
    assert overrides.min_font_size == 48
    assert overrides.max_font_size == 120


def test_alternate_config_remains_beneath_explicit_viewer_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    config_path.write_text(
        _CONFIG.replace("min_font_size: 28, max_font_size: 100", "min_font_size: 36, max_font_size: 140")
    )
    bounds: list[tuple[int, int]] = []
    layout = preparation.layout_composition

    def capture(*args, **kwargs):
        bounds.append((args[4], args[5]))
        return layout(*args, **kwargs)

    monkeypatch.setattr(preparation, "layout_composition", capture)

    assert (
        viewer.main(
            [
                "--config",
                str(config_path),
                "--entry",
                "@preview:1",
                "--min-font-size",
                "48",
                "--resolution",
                "320",
                "200",
                "--output",
                str(tmp_path / "preview.png"),
            ]
        )
        == 0
    )
    assert bounds == [(4, 12)]


@pytest.mark.parametrize(
    ("configured_minimum", "configured_maximum", "overrides", "expected_design_bounds"),
    [
        (28, 100, PresentationOverrides(min_font_size=48), (48, 100)),
        (28, 100, PresentationOverrides(max_font_size=120), (28, 120)),
        (28, 100, PresentationOverrides(), (28, 100)),
        (28, 100, PresentationOverrides(min_font_size=60, max_font_size=80), (60, 80)),
        (36, 140, PresentationOverrides(min_font_size=48), (48, 140)),
    ],
)
def test_font_size_overrides_precede_each_selected_configuration_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_minimum: int,
    configured_maximum: int,
    overrides: PresentationOverrides,
    expected_design_bounds: tuple[int, int],
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    config_path.write_text(
        _CONFIG.replace(
            "min_font_size: 28, max_font_size: 100",
            f"min_font_size: {configured_minimum}, max_font_size: {configured_maximum}",
        ),
        encoding="utf-8",
    )
    configuration = load_application_config(config_path)
    specification = viewer._output_specification("16:10", (320, 200))

    bounds = _capture_rendered_bounds(monkeypatch, configuration, ("@preview", 1), specification, overrides)

    assert bounds == tuple(max(1, preparation.round_half_up(value * 320, 3840)) for value in expected_design_bounds)


@pytest.mark.parametrize(
    ("arguments", "configured_minimum", "configured_maximum"),
    [
        (["--min-font-size", "120"], 28, 100),
        (["--max-font-size", "20"], 28, 100),
        (["--min-font-size", "60", "--max-font-size", "40"], 28, 100),
    ],
)
def test_cli_rejects_invalid_effective_font_size_ranges(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    configured_minimum: int,
    configured_maximum: int,
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    config_path.write_text(
        _CONFIG.replace(
            "min_font_size: 28, max_font_size: 100",
            f"min_font_size: {configured_minimum}, max_font_size: {configured_maximum}",
        ),
        encoding="utf-8",
    )

    assert (
        viewer.main(
            [
                "--config",
                str(config_path),
                "--entry",
                "@preview:1",
                *arguments,
                "--output",
                str(tmp_path / "preview.png"),
            ]
        )
        == 1
    )
    assert "invalid effective font-size range" in capsys.readouterr().err
    assert not (tmp_path / "preview.png").exists()


@pytest.mark.parametrize(
    ("resolution", "expected_bounds"),
    [
        (None, (48, 120)),
        ((1920, 1200), (24, 60)),
        ((1600, 900), (19, 49)),
    ],
)
def test_font_size_overrides_scale_from_design_canvas_not_requested_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolution: tuple[int, int] | None,
    expected_bounds: tuple[int, int],
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    specification = viewer._output_specification("16:10", resolution)

    bounds = _capture_rendered_bounds(
        monkeypatch,
        configuration,
        ("@preview", 1),
        specification,
        PresentationOverrides(min_font_size=48, max_font_size=120),
    )

    assert bounds == expected_bounds
    if resolution is not None:
        assert specification.requested_output_size == resolution
    if resolution == (1600, 900):
        assert specification.presentation_canvas_size != resolution


@pytest.mark.parametrize("quotation_number", [1, 3])
def test_viewer_automatic_fitting_obeys_shared_effective_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quotation_number: int,
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    specification = viewer._output_specification("16:10", (1920, 1200))
    rendered_sizes: list[int] = []
    layout = preparation.layout_composition

    def capture(*args, **kwargs):
        fitted = layout(*args, **kwargs)
        rendered_sizes.append(fitted.quotation.font_size)
        return fitted

    monkeypatch.setattr(preparation, "layout_composition", capture)
    image = viewer.render_preview(configuration, ("@preview", quotation_number), specification)
    image.close()
    assert (
        viewer.main(
            [
                "--config",
                str(config_path),
                "--entry",
                f"@preview:{quotation_number}",
                "--min-font-size",
                "40",
                "--max-font-size",
                "40",
                "--resolution",
                "1920",
                "1200",
                "--output",
                str(tmp_path / "constrained.png"),
            ]
        )
        == 0
    )

    assert rendered_sizes[0] > 20
    assert rendered_sizes[1] == 20


def test_debug_layout_cli_uses_shared_literary_qr_and_nine_slice_overlays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
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

    output = tmp_path / "debug.png"
    assert (
        viewer.main(
            [
                "--config",
                str(config_path),
                "--entry",
                "@preview:2",
                "--resolution",
                "160",
                "100",
                "--output",
                str(output),
                "--debug-layout",
            ]
        )
        == 0
    )
    with Image.open(output) as image:
        assert image.getpixel((10, 50)) == (127, 127, 127)
        assert image.getpixel((100, 65)) == (255, 0, 255)
        assert image.getpixel((30, 50)) == (255, 25, 25)


def test_runtime_and_viewer_share_presentation_construction_and_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    entry, quotation = viewer._select_entry(configuration, ("@preview", 2))
    runtime_snapshot = application._build_snapshot(configuration, entry, quotation, date.today())
    viewer_snapshot = build_presentation_snapshot(configuration, entry, quotation, date.today())
    resolutions = []
    layout_bounds: list[tuple[int, int]] = []
    resolve_choices = preparation._resolve_presentation_choices
    layout = preparation.layout_composition

    def capture_resolution(*args, **kwargs):
        resolutions.append(kwargs["overrides"])
        return resolve_choices(*args, **kwargs)

    def capture_layout(*args, **kwargs):
        layout_bounds.append((args[4], args[5]))
        return layout(*args, **kwargs)

    monkeypatch.setattr(preparation, "_resolve_presentation_choices", capture_resolution)
    monkeypatch.setattr(preparation, "layout_composition", capture_layout)
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
            overrides=PresentationOverrides(style="left-aligned", min_font_size=48, max_font_size=120),
        )
        viewer_image.close()
    finally:
        for images in runtime_images.values():
            for image in images:
                image.close()

    assert runtime_snapshot == viewer_snapshot
    assert len(resolutions) == 2
    assert resolutions[0] == PresentationOverrides()
    assert resolutions[1] == PresentationOverrides(style="left-aligned", min_font_size=48, max_font_size=120)
    assert layout_bounds == [(2, 8), (4, 10)]

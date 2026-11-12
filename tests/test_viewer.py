from __future__ import annotations

import struct
import zlib
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
from refrain.display.coordinator import PublicationResult, PublicationStatus
from refrain.geometry import ResolvedOutputSpecification
from refrain.preparation import PresentationOverrides, prepare_daily_images
from refrain.presentation import build_presentation_snapshot
from refrain.runtime_control import (
    RuntimeAuthenticationError,
    RuntimeProtocolError,
    RuntimeUnavailable,
    RuntimeUnconfirmed,
    RuntimeUnsupportedProtocol,
)
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


def test_finished_png_local_inspection_avoids_configuration_and_closes_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / "finished.png"
    source = Image.new("RGB", (32, 24), (10, 20, 30))
    source.save(source_path)
    source.close()
    loaded_images = []
    load_finished_image = viewer._load_finished_image

    def load_image(path):
        image = load_finished_image(path)
        loaded_images.append(image)
        return image

    def show(image):
        assert image.size == (32, 24)
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (10, 20, 30)

    monkeypatch.setattr(viewer, "_load_finished_image", load_image)
    monkeypatch.setattr(viewer, "show_preview_window", show)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("configuration loaded"))
    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: pytest.fail("application paths resolved"))

    assert viewer.main(["--image", str(source_path), "--window"]) == 0

    _assert_image_closed(loaded_images[0])
    with Image.open(source_path) as original:
        assert original.size == (32, 24)
        assert original.getpixel((0, 0)) == (10, 20, 30)


@pytest.mark.parametrize(
    ("kind", "diagnostic"),
    [
        ("missing", "cannot read finished PNG"),
        ("jpeg", "must be a PNG"),
        ("rgba", "must use RGB mode"),
        ("palette", "must use RGB mode"),
        ("animated", "exactly one frame"),
        ("corrupt", "cannot read finished PNG"),
    ],
)
def test_finished_png_validation_rejects_unsupported_inputs(tmp_path: Path, kind: str, diagnostic: str) -> None:
    path = tmp_path / "source.png"
    if kind == "missing":
        path = tmp_path / "missing.png"
    elif kind == "jpeg":
        Image.new("RGB", (8, 6)).save(path, format="JPEG")
    elif kind == "rgba":
        Image.new("RGBA", (8, 6)).save(path, format="PNG")
    elif kind == "palette":
        Image.new("P", (8, 6)).save(path, format="PNG")
    elif kind == "animated":
        first = Image.new("RGB", (8, 6), "red")
        second = Image.new("RGB", (8, 6), "blue")
        first.save(path, format="PNG", save_all=True, append_images=[second])
        first.close()
        second.close()
    elif kind == "corrupt":
        valid = Image.new("RGB", (8, 6))
        valid.save(path, format="PNG")
        valid.close()
        path.write_bytes(path.read_bytes()[:-20])

    with pytest.raises(viewer.ViewerError, match=diagnostic):
        viewer._load_finished_image(path)


def test_finished_png_rejects_16_bit_rgb_that_pillow_would_reduce(tmp_path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    scanline = b"\x00" + struct.pack(">HHH", 0x1234, 0x5678, 0x9ABC)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 16, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanline))
        + chunk(b"IEND", b"")
    )
    path = tmp_path / "16-bit-rgb.png"
    path.write_bytes(png)

    with Image.open(path) as source:
        assert source.mode == "RGB"
        assert source.getpixel((0, 0)) == (18, 86, 154)

    with pytest.raises(viewer.ViewerError, match="8-bit RGB"):
        viewer._load_finished_image(path)


def test_finished_png_window_failure_is_actionable_and_closes_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_path = tmp_path / "finished.png"
    Image.new("RGB", (32, 24)).save(source_path)
    loaded_images = []
    load_image = viewer._load_finished_image

    def track_image(path):
        image = load_image(path)
        loaded_images.append(image)
        return image

    monkeypatch.setattr(viewer, "_load_finished_image", track_image)

    def unavailable(_image):
        raise viewer.ViewerError("window display is unavailable")

    monkeypatch.setattr(viewer, "show_preview_window", unavailable)

    assert viewer.main(["--image", str(source_path)]) == 1
    assert "window display is unavailable" in capsys.readouterr().err
    _assert_image_closed(loaded_images[0])


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


def _push_destination(
    identifier: str,
    specification: ResolvedOutputSpecification,
    *,
    participating: bool = True,
    withdrawn: bool = False,
    available: bool = True,
    supports_transient: bool = True,
) -> dict[str, object]:
    return {
        "identifier": identifier,
        "output_specification": specification,
        "supports_transient": supports_transient,
        "participating": participating,
        "withdrawn": withdrawn,
        "available": available,
    }


def _assert_image_closed(image: Image.Image) -> None:
    with pytest.raises(ValueError, match="closed"):
        image.getpixel((0, 0))


@pytest.mark.parametrize(
    "arguments",
    [
        ["--image", "candidate.png"],
        ["--image", "candidate.png", "--push", "window"],
        ["--image", "candidate.png", "--push", "all"],
    ],
)
def test_finished_image_arguments_parse(arguments: list[str]) -> None:
    parsed = viewer._parser().parse_args(arguments)

    assert parsed.image == Path("candidate.png")
    assert parsed.push == (arguments[-1] if "--push" in arguments else None)


@pytest.mark.parametrize(
    ("extra_arguments", "diagnostic"),
    [
        (["--config", "config.yaml"], "--config"),
        (["--entry", "entry"], "--entry"),
        (["--font", "font"], "--font"),
        (["--quotation-face", "face"], "--quotation-face"),
        (["--source-face", "face"], "--source-face"),
        (["--attribution-face", "face"], "--attribution-face"),
        (["--min-font-size", "12"], "--min-font-size"),
        (["--max-font-size", "20"], "--max-font-size"),
        (["--background", "paper"], "--background"),
        (["--decoration", "border"], "--decoration"),
        (["--text-color", "black"], "--text-color"),
        (["--tint", "blue"], "--tint"),
        (["--style", "centered"], "--style"),
        (["--qr"], "--qr/--no-qr"),
        (["--no-qr"], "--qr/--no-qr"),
        (["--aspect", "16:9"], "--aspect"),
        (["--resolution", "320", "200"], "--resolution"),
        (["--output", "copy.png"], "--output"),
        (["--debug-layout"], "--debug-layout"),
        (["--list-destinations"], "--image"),
    ],
)
def test_finished_image_rejects_presentation_and_geometry_controls(
    extra_arguments: list[str], diagnostic: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "run_image_viewer", lambda *_: pytest.fail("image viewer was started"))

    with pytest.raises(SystemExit) as error:
        viewer.main(["--image", "candidate.png", *extra_arguments])

    assert error.value.code == 2
    assert diagnostic in capsys.readouterr().err


def test_finished_image_push_rejects_presentation_controls(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "_run_push", lambda *_args, **_kwargs: pytest.fail("push was dispatched"))

    with pytest.raises(SystemExit) as error:
        viewer.main(["--image", "candidate.png", "--push", "window", "--style", "centered"])

    assert error.value.code == 2
    assert "--style" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("arguments", "diagnostic"),
    [
        (["--push", "window", "--window"], "--window"),
        (["--push", "window", "--output", "preview.png"], "--output"),
        (["--push", "window", "--aspect", "16:9"], "--aspect"),
        (["--push", "window", "--resolution", "320", "200"], "--resolution"),
        (["--push", "window", "--list-destinations"], "--list-destinations"),
    ],
)
def test_push_rejects_local_output_and_discovery_conflicts(
    arguments: list[str], diagnostic: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "_run_push", lambda *_args, **_kwargs: pytest.fail("push was dispatched"))

    with pytest.raises(SystemExit) as error:
        viewer.main(arguments)

    assert error.value.code == 2
    assert diagnostic in capsys.readouterr().err


def test_push_arguments_keep_presentation_selection_and_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(viewer, "_run_push", lambda target, **kwargs: captured.update(target=target, **kwargs) or 0)

    assert (
        viewer.main(
            [
                "--config",
                "custom.yaml",
                "--entry",
                "johnson-maggie:6",
                "--font",
                "lora",
                "--decoration",
                "simple-border",
                "--no-qr",
                "--push",
                "image-server:wquxga",
            ]
        )
        == 0
    )
    assert captured["target"] == "image-server:wquxga"
    assert captured["config_file"] == "custom.yaml"
    assert captured["selector"] == ("johnson-maggie", 6)
    overrides = captured["overrides"]
    assert isinstance(overrides, PresentationOverrides)
    assert overrides.font == "lora"
    assert overrides.decoration == "simple-border"
    assert overrides.qr_enabled is False


@pytest.mark.parametrize(
    ("target", "destinations", "diagnostic"),
    [
        ("missing", (_push_destination("window", ResolvedOutputSpecification("16:9", (320, 180))),), "unknown"),
        (
            "withdrawn",
            (
                _push_destination(
                    "withdrawn",
                    ResolvedOutputSpecification("16:9", (320, 180)),
                    participating=False,
                    withdrawn=True,
                ),
            ),
            "intentionally withdrawn",
        ),
        (
            "unsupported",
            (
                _push_destination(
                    "unsupported",
                    ResolvedOutputSpecification("16:9", (320, 180)),
                    supports_transient=False,
                ),
            ),
            "unsupported",
        ),
        (
            "all",
            (
                _push_destination(
                    "unsupported",
                    ResolvedOutputSpecification("16:9", (320, 180)),
                    supports_transient=False,
                ),
            ),
            "unsupported",
        ),
        ("all", (), "no resident destinations remain participating"),
        (
            "all",
            (
                _push_destination(
                    "withdrawn",
                    ResolvedOutputSpecification("16:9", (320, 180)),
                    participating=False,
                    withdrawn=True,
                ),
            ),
            "no resident destinations remain participating",
        ),
    ],
)
def test_push_rejects_invalid_discovered_destinations_before_loading_or_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    destinations: tuple[dict[str, object], ...],
    diagnostic: str,
) -> None:
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return destinations

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("configuration loaded"))
    monkeypatch.setattr(viewer, "render_preview_variants", lambda *_args, **_kwargs: pytest.fail("rendered"))

    assert viewer.main(["--push", target]) == 1
    assert diagnostic in capsys.readouterr().err


def test_image_push_discovers_before_loading_and_publishes_exact_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image_path = tmp_path / "finished.png"
    source = Image.new("RGB", (320, 240), (10, 20, 30))
    source.save(image_path)
    source.close()
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    specification = ResolvedOutputSpecification("4:3", (320, 240))
    destination = _push_destination("screen", specification, available=False)
    calls = []
    loaded_images = []
    load_finished_image = viewer._load_finished_image

    def load_image(path):
        image = load_finished_image(path)
        loaded_images.append(image)
        calls.append("load-image")
        return image

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            calls.append("discover")
            return (destination,)

        def publish_transient(self, target, specifications, images, *, on_accepted):
            calls.append("publish")
            assert target == "screen"
            assert specifications == {"screen": specification}
            assert set(images) == {specification}
            image = images[specification]
            assert image.mode == "RGB"
            assert image.size == (320, 240)
            assert image.getpixel((0, 0)) == (10, 20, 30)
            on_accepted()
            return PublicationResult(PublicationStatus.SUCCEEDED, {"screen": (True, None)})

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", load_image)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("configuration loaded"))
    monkeypatch.setattr(viewer, "render_preview_variants", lambda *_args, **_kwargs: pytest.fail("renderer invoked"))

    assert viewer.main(["--image", str(image_path), "--push", "screen"]) == 0
    assert calls == ["discover", "load-image", "publish"]
    output = capsys.readouterr().out
    assert "Push accepted; publication has begun." in output
    assert "Push completed successfully." in output
    _assert_image_closed(loaded_images[0])


def test_image_push_rejects_mismatched_dimensions_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image_path = tmp_path / "finished.png"
    Image.new("RGB", (640, 480)).save(image_path)
    specification = ResolvedOutputSpecification("16:9", (320, 180))
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    loaded_images = []

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (_push_destination("display", specification),)

        def publish_transient(self, *_args, **_kwargs):
            pytest.fail("mismatched image was submitted")

    load_image = viewer._load_finished_image

    def track_image(path):
        image = load_image(path)
        loaded_images.append(image)
        return image

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", track_image)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("configuration loaded"))

    assert viewer.main(["--image", str(image_path), "--push", "display"]) == 1
    diagnostic = capsys.readouterr().err
    assert "image is 640x480" in diagnostic
    assert "destination 'display' requires 320x180" in diagnostic
    _assert_image_closed(loaded_images[0])


def test_image_push_all_preserves_destination_specs_and_reuses_same_raster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image_path = tmp_path / "finished.png"
    Image.new("RGB", (320, 240), (10, 20, 30)).save(image_path)
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    specifications = {
        "available": ResolvedOutputSpecification("4:3", (320, 240)),
        "unavailable": ResolvedOutputSpecification("16:10", (320, 240)),
    }
    destinations = (
        _push_destination("available", specifications["available"]),
        _push_destination("unavailable", specifications["unavailable"], available=False),
        _push_destination(
            "withdrawn",
            ResolvedOutputSpecification("16:9", (320, 180)),
            participating=False,
            withdrawn=True,
        ),
    )
    loaded_images = []

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return destinations

        def publish_transient(self, target, destination_specs, images, *, on_accepted):
            assert target == "all"
            assert destination_specs == specifications
            assert set(images) == set(specifications.values())
            assert images[specifications["available"]] is images[specifications["unavailable"]]
            assert all(image.size == (320, 240) for image in images.values())
            assert all(image.getpixel((0, 0)) == (10, 20, 30) for image in images.values())
            on_accepted()
            return PublicationResult(
                PublicationStatus.SUCCEEDED,
                {identifier: (True, None) for identifier in destination_specs},
            )

    load_image = viewer._load_finished_image

    def track_image(path):
        image = load_image(path)
        loaded_images.append(image)
        return image

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", track_image)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("configuration loaded"))
    monkeypatch.setattr(viewer, "render_preview_variants", lambda *_args, **_kwargs: pytest.fail("renderer invoked"))

    assert viewer.main(["--image", str(image_path), "--push", "all"]) == 0
    assert "Push accepted; publication has begun." in capsys.readouterr().out
    _assert_image_closed(loaded_images[0])


def test_image_push_all_mismatch_rejects_every_destination_before_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image_path = tmp_path / "finished.png"
    source = Image.new("RGB", (320, 240))
    source.save(image_path)
    source.close()
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    destinations = (
        _push_destination("matching", ResolvedOutputSpecification("4:3", (320, 240))),
        _push_destination("different", ResolvedOutputSpecification("16:9", (320, 180))),
    )
    loaded_images = []
    load_finished_image = viewer._load_finished_image

    def track_image(path):
        image = load_finished_image(path)
        loaded_images.append(image)
        return image

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return destinations

        def publish_transient(self, *_args, **_kwargs):
            pytest.fail("partially matching image was submitted")

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", track_image)

    assert viewer.main(["--image", str(image_path), "--push", "all"]) == 1
    diagnostic = capsys.readouterr().err
    assert "destination 'different' requires 320x180" in diagnostic
    _assert_image_closed(loaded_images[0])


def test_image_push_rejects_unknown_destination_before_loading_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    destination = _push_destination("screen", ResolvedOutputSpecification("4:3", (320, 240)))

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (destination,)

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", lambda *_: pytest.fail("image was loaded"))

    assert viewer.main(["--image", "missing.png", "--push", "unknown"]) == 1
    assert "destination 'unknown' is unknown" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("target", "destination", "diagnostic"),
    [
        (
            "withdrawn",
            _push_destination(
                "withdrawn",
                ResolvedOutputSpecification("4:3", (320, 240)),
                participating=False,
                withdrawn=True,
            ),
            "intentionally withdrawn",
        ),
        (
            "unsupported",
            _push_destination(
                "unsupported",
                ResolvedOutputSpecification("4:3", (320, 240)),
                supports_transient=False,
            ),
            "unsupported",
        ),
        (
            "all",
            _push_destination(
                "unsupported",
                ResolvedOutputSpecification("4:3", (320, 240)),
                supports_transient=False,
            ),
            "unsupported",
        ),
    ],
)
def test_image_push_rejects_ineligible_destination_before_loading_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    destination: dict[str, object],
    diagnostic: str,
) -> None:
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (destination,)

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", lambda *_: pytest.fail("image was loaded"))

    assert viewer.main(["--image", "missing.png", "--push", target]) == 1
    assert diagnostic in capsys.readouterr().err


@pytest.mark.parametrize(
    ("outcome", "diagnostic"),
    [
        (PublicationResult(PublicationStatus.BUSY, {}), "busy"),
        (
            PublicationResult(PublicationStatus.FAILED, {"screen": (False, "device timed out")}),
            "push publication failed",
        ),
        (RuntimeUnconfirmed("publication outcome is unconfirmed"), "publication may have occurred"),
        (RuntimeAuthenticationError("runtime-control authentication failed"), "restart the resident Refrain runtime"),
        (RuntimeProtocolError("invalid publication response"), "runtime-control request failed"),
        (RuntimeUnavailable("resident runtime connection lost"), "resident runtime connection lost"),
    ],
)
def test_image_push_closes_image_after_terminal_runtime_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: PublicationResult | Exception,
    diagnostic: str,
) -> None:
    image_path = tmp_path / "finished.png"
    Image.new("RGB", (320, 240)).save(image_path)
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    specification = ResolvedOutputSpecification("4:3", (320, 240))
    loaded_images = []
    load_finished_image = viewer._load_finished_image

    def track_image(path):
        image = load_finished_image(path)
        loaded_images.append(image)
        return image

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (_push_destination("screen", specification),)

        def publish_transient(self, _target, _specifications, _images, *, on_accepted):
            if isinstance(outcome, RuntimeUnconfirmed):
                on_accepted()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "_load_finished_image", track_image)

    assert viewer.main(["--image", str(image_path), "--push", "screen"]) == 1
    assert diagnostic in capsys.readouterr().err
    _assert_image_closed(loaded_images[0])


def test_push_all_uses_discovery_geometry_deduplicates_images_and_reports_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    specs = (
        ResolvedOutputSpecification("4:3", (320, 240)),
        ResolvedOutputSpecification("5:3", (320, 192)),
        ResolvedOutputSpecification("16:9", (320, 180)),
    )
    destinations = (
        _push_destination("window", specs[0]),
        _push_destination("failed:display", specs[1], available=False),
        _push_destination("image-server:first", specs[2]),
        _push_destination("image-server:second", specs[0]),
        _push_destination(
            "withdrawn",
            ResolvedOutputSpecification("16:9", (640, 360)),
            participating=False,
            withdrawn=True,
            supports_transient=False,
        ),
    )
    calls: list[str] = []
    rendered: dict[ResolvedOutputSpecification, Image.Image] = {}
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            calls.append("discover")
            return destinations

        def publish_transient(self, target, specifications, images, *, on_accepted):
            calls.append("publish")
            captured.update(target=target, specifications=specifications, images=images)
            assert target == "all"
            assert specifications == {
                "window": specs[0],
                "failed:display": specs[1],
                "image-server:first": specs[2],
                "image-server:second": specs[0],
            }
            assert set(images) == set(specs)
            assert all(
                image.mode == "RGB" and image.size == spec.requested_output_size for spec, image in images.items()
            )
            on_accepted()
            captured["accepted_output"] = capsys.readouterr().out
            return PublicationResult(
                PublicationStatus.SUCCEEDED,
                {identifier: (True, None) for identifier in specifications},
            )

    def load_configuration(path):
        calls.append("load")
        return configuration

    def render(_configuration, selector, output_specifications, **kwargs):
        calls.append("render")
        assert selector == ("@preview", 2)
        assert set(output_specifications) == set(specs)
        assert kwargs["overrides"].qr_enabled is False
        rendered.update({spec: Image.new("RGB", spec.requested_output_size, "white") for spec in output_specifications})
        return rendered

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", load_configuration)
    monkeypatch.setattr(viewer, "render_preview_variants", render)

    assert viewer.main(["--config", str(config_path), "--no-qr", "--push", "all"]) == 0
    assert calls == ["discover", "load", "render", "publish"]
    output = capsys.readouterr().out
    assert "Push accepted; publication has begun." in captured["accepted_output"]
    assert "Push completed successfully." in output
    for image in rendered.values():
        _assert_image_closed(image)
    assert captured["images"] == rendered


def test_explicit_push_preserves_destination_and_failed_participation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    spec = ResolvedOutputSpecification("16:9", (320, 180))
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    destination = _push_destination("opaque:id", spec, available=False)
    image = Image.new("RGB", spec.requested_output_size)
    captured = {}

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (destination,)

        def publish_transient(self, target, specifications, images, *, on_accepted):
            captured.update(target=target, specifications=specifications, images=images)
            on_accepted()
            return PublicationResult(PublicationStatus.SUCCEEDED, {"opaque:id": (True, None)})

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: configuration)
    monkeypatch.setattr(viewer, "render_preview_variants", lambda *_args, **_kwargs: {spec: image})

    assert viewer.main(["--config", str(config_path), "--push", "opaque:id"]) == 0
    assert captured["target"] == "opaque:id"
    assert captured["specifications"] == {"opaque:id": spec}
    assert captured["images"] == {spec: image}
    _assert_image_closed(image)
    assert "Push completed successfully." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("result", "diagnostics"),
    [
        (PublicationResult(PublicationStatus.BUSY, {}), ("busy",)),
        (
            PublicationResult(PublicationStatus.FAILED, {"screen": (False, "device timed out")}),
            ("publication failed", "screen", "device timed out"),
        ),
        (PublicationResult(PublicationStatus.SUCCEEDED, {}), ("no terminal outcome reported",)),
    ],
)
def test_push_reports_busy_and_per_destination_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: PublicationResult,
    diagnostics: tuple[str, ...],
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    spec = ResolvedOutputSpecification("16:9", (320, 180))
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    rendered = Image.new("RGB", spec.requested_output_size)

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (_push_destination("screen", spec),)

        def publish_transient(self, *_args, **_kwargs):
            return result

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: configuration)
    monkeypatch.setattr(viewer, "render_preview_variants", lambda *_args, **_kwargs: {spec: rendered})

    assert viewer.main(["--config", str(config_path), "--push", "screen"]) == 1
    error = capsys.readouterr().err
    assert all(diagnostic in error for diagnostic in diagnostics)
    _assert_image_closed(rendered)


@pytest.mark.parametrize(
    ("error", "diagnostic"),
    [
        (RuntimeUnavailable("No resident Refrain runtime is available"), "No resident Refrain"),
        (RuntimeAuthenticationError("runtime-control authentication failed"), "authentication failed"),
        (RuntimeUnsupportedProtocol("unsupported runtime-control protocol"), "versions are compatible"),
        (RuntimeProtocolError("invalid publication response"), "runtime-control protocol error"),
    ],
)
def test_push_control_errors_are_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    diagnostic: str,
) -> None:
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            raise error

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: pytest.fail("configuration loaded"))

    assert viewer.main(["--push", "screen"]) == 1
    assert diagnostic in capsys.readouterr().err


@pytest.mark.parametrize(
    ("outcome", "expected_diagnostic"),
    [
        (RuntimeProtocolError("invalid publication response"), "runtime-control request failed"),
        (RuntimeUnconfirmed("publication outcome is unconfirmed"), "publication may have occurred"),
        (RuntimeUnavailable("resident runtime connection lost"), "resident runtime connection lost"),
    ],
)
def test_push_closes_images_when_submission_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: Exception,
    expected_diagnostic: str,
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    spec = ResolvedOutputSpecification("16:9", (320, 180))
    paths = SimpleNamespace(control_metadata_file=tmp_path / "endpoint.json")
    rendered = Image.new("RGB", spec.requested_output_size)

    class Client:
        def __init__(self, _metadata_path: Path) -> None:
            pass

        def discover(self):
            return (_push_destination("screen", spec),)

        def publish_transient(self, *_args, **_kwargs):
            raise outcome

    monkeypatch.setattr(viewer, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(viewer, "RuntimeControlClient", Client)
    monkeypatch.setattr(viewer, "load_application_config", lambda *_: configuration)
    monkeypatch.setattr(viewer, "render_preview_variants", lambda *_args, **_kwargs: {spec: rendered})

    assert viewer.main(["--config", str(config_path), "--push", "screen"]) == 1
    assert expected_diagnostic in capsys.readouterr().err
    _assert_image_closed(rendered)


def test_render_preview_variants_use_discovered_specs_and_shared_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _ = _workspace(tmp_path, with_entry=False)
    configuration = load_application_config(config_path)
    specifications = (
        ResolvedOutputSpecification("4:3", (320, 240)),
        ResolvedOutputSpecification("5:3", (320, 192)),
        ResolvedOutputSpecification("16:9", (320, 180)),
    )
    choices_seen = []
    prepare_one = preparation._prepare_daily_images_for_specification

    def capture_choices(*args, **kwargs):
        choices_seen.append(args[4])
        return prepare_one(*args, **kwargs)

    monkeypatch.setattr(preparation, "_prepare_daily_images_for_specification", capture_choices)
    images = viewer.render_preview_variants(
        configuration,
        ("@preview", 2),
        (*specifications, specifications[0]),
        overrides=PresentationOverrides(qr_enabled=False),
    )
    try:
        assert set(images) == set(specifications)
        assert len(choices_seen) == len(specifications)
        assert all(choice is choices_seen[0] for choice in choices_seen)
        for specification, image in images.items():
            assert image.mode == "RGB"
            assert image.size == specification.requested_output_size
    finally:
        for image in images.values():
            image.close()

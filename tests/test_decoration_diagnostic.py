from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from PIL import Image

import refrain.__main__ as cli
import refrain.application as application
import refrain.decoration_diagnostic as diagnostic
from refrain.qr import PRODUCTION_QR_PARAMETERS, render_qr_code, resolve_qr_placement

_CONFIG = """\
display:
  backends:
    - type: window
    - type: image-server
layout:
  presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}
  fonts:
    default: [lora]
  backgrounds:
    default: [none]
  decorations:
    default: [none]
  text:
    min_font_size: 20
    max_font_size: 100
"""

_MANIFEST = """\
format: 1
id: a-custom
layers:
  - image: artwork.png
    method: contain
presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}
font: lora
font_faces: {quotation: italic}
background: none
text_color: red
tintable: true
decoration_color: blue
"""


class RecordingBackend:
    def __init__(self):
        self.images = []
        self.closed = False

    def update(self, image):
        self.images.append(image.copy())

    def close(self):
        self.closed = True


@pytest.fixture
def workspace(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    package = tmp_path / "assets" / "decorations" / "nested" / "package"
    package.mkdir(parents=True)
    (package / "decoration.yaml").write_text(_MANIFEST, encoding="utf-8")
    with Image.new("RGBA", (80, 60), (0, 0, 0, 255)) as image:
        image.save(package / "artwork.png")
    return config, package


def input_keys(keys):
    @contextmanager
    def reader():
        yield iter(keys).__next__

    return reader


def test_sequence_discovery_controls_and_isolation(workspace, monkeypatch, capsys):
    config, _ = workspace
    snapshots = []
    render = diagnostic._render

    def capture(*args):
        image, snapshot = render(*args)
        snapshots.append(snapshot)
        return image, snapshot

    def forbidden(*args, **kwargs):
        pytest.fail("diagnostic must not select or load user content")

    monkeypatch.setattr(diagnostic, "_render", capture)
    monkeypatch.setattr(application, "load_content_library", forbidden)
    monkeypatch.setattr(application, "select_quotation", forbidden)
    backends = {name: RecordingBackend() for name in ("window", "image-server")}
    diagnostic.run_decoration_diagnostic(
        config,
        backend_factory=lambda settings: backends[settings.type],
        input_factory=input_keys(["x", " ", "B", "b", " ", "r", "R", "q"]),
    )
    ids = [snapshot.decoration for snapshot in snapshots]
    assert ids == ["a-custom", "a-custom", "a-custom", "top-bottom-borders", "a-custom", "a-custom", "a-custom"]
    assert snapshots[0].quotation_text == snapshots[2].quotation_text == snapshots[4].quotation_text
    assert snapshots[0].quotation_text != snapshots[1].quotation_text
    assert all(snapshot.source and snapshot.attribution for snapshot in snapshots)
    output = capsys.readouterr().out
    assert "Presentation: 1 of 12" in output
    assert "Quotation: SHORT" in output and "Quotation: LONG" in output
    assert "Literary output bounds: (192, 162, 1728, 918)" in output
    first, second = backends.values()
    assert len(first.images) == len(second.images) == len(snapshots)
    assert [image.tobytes() for image in first.images] == [image.tobytes() for image in second.images]
    assert first.images[0].tobytes() == first.images[4].tobytes() == first.images[5].tobytes()
    assert first.closed and second.closed
    for backend in backends.values():
        for image in backend.images:
            image.close()
    assert not (config.parent / "content").exists()
    assert not list(config.parent.glob("*.json"))


def test_variants_share_visual_choices_across_navigation_and_reload(workspace, monkeypatch):
    config, package = workspace
    config.write_text(
        _CONFIG.replace("default: [lora]", "default: [lora, alegreya, source-sans-3]")
        .replace("default: [none]\n  decorations:", "default: [none, canvas, cloth]\n  decorations:")
        .replace("    min_font_size:", "    colors: [black, red, blue]\n    min_font_size:"),
        encoding="utf-8",
    )
    manifest = (
        _MANIFEST.replace("font: lora\n", "")
        .replace("background: none\n", "")
        .replace("text_color: red", "text_color: [black, red, blue]")
        .replace("decoration_color: blue", "decoration_color: [black, red, blue]")
    )
    manifest_file = package / "decoration.yaml"
    manifest_file.write_text(manifest, encoding="utf-8")
    other = package.parent / "other"
    other.mkdir()
    (other / "decoration.yaml").write_text(manifest.replace("a-custom", "b-custom"), encoding="utf-8")
    with Image.new("RGBA", (80, 60), (0, 0, 0, 64)) as image:
        image.save(package / "artwork.png")
        image.save(other / "artwork.png")

    snapshots = []
    render = diagnostic._render

    def capture(*args):
        image, snapshot = render(*args)
        snapshots.append(snapshot)
        return image, snapshot

    monkeypatch.setattr(diagnostic, "_render", capture)
    backends = {name: RecordingBackend() for name in ("window", "image-server")}

    @contextmanager
    def reader():
        keys = iter([" ", "b", "r", " ", " ", " ", "b", "b", "b", "r", " ", "q"])
        count = 0

        def read():
            nonlocal count
            count += 1
            if count == 10:
                updated = (
                    manifest.replace("font_faces:", "font: alegreya\nbackground: canvas\nfont_faces:")
                    .replace("text_color: [black, red, blue]", "text_color: red")
                    .replace("decoration_color: [black, red, blue]", "decoration_color: blue")
                )
                manifest_file.write_text(updated, encoding="utf-8")
            return next(keys)

        yield read

    diagnostic.run_decoration_diagnostic(
        config, backend_factory=lambda settings: backends[settings.type], input_factory=reader
    )

    def choices(snapshot):
        return (
            snapshot.decoration,
            snapshot.font,
            snapshot.background,
            snapshot.font_faces,
            snapshot.text_color,
            snapshot.decoration_color,
        )

    assert [s.decoration for s in snapshots] == [
        "a-custom",
        "a-custom",
        "a-custom",
        "a-custom",
        "a-custom",
        "b-custom",
        "b-custom",
        "b-custom",
        "a-custom",
        "a-custom",
        "a-custom",
        "a-custom",
    ]
    assert all(choices(snapshots[index]) == choices(snapshots[0]) for index in (1, 2, 3, 4, 8, 9))
    assert choices(snapshots[5]) != choices(snapshots[0])
    assert choices(snapshots[5]) == choices(snapshots[6]) == choices(snapshots[7])
    assert choices(snapshots[10]) == choices(snapshots[11])
    assert snapshots[10].font is None
    assert snapshots[10].background is None
    assert snapshots[10].text_color is None
    assert snapshots[10].decoration_color is None
    assert snapshots[0].quotation_text != snapshots[1].quotation_text
    assert snapshots[0].source != snapshots[1].source
    for backend in backends.values():
        assert backend.images[0].tobytes() != backend.images[1].tobytes()
        assert backend.images[0].tobytes() == backend.images[2].tobytes() == backend.images[3].tobytes()
        assert backend.images[1].tobytes() == backend.images[4].tobytes() == backend.images[8].tobytes()
        for image in backend.images:
            image.close()


def test_reload_invalid_recover_image_manifest_and_debug_region(workspace, capsys):
    config, package = workspace
    manifest = package / "decoration.yaml"
    backend = RecordingBackend()
    actions = iter(["r", "R", "r", "r", "Q"])
    count = 0

    @contextmanager
    def reader():
        def read():
            nonlocal count
            count += 1
            if count == 1:
                manifest.write_text("invalid: [", encoding="utf-8")
            elif count == 2:
                manifest.write_text(
                    _MANIFEST.replace(
                        "presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}",
                        "presentation_insets: {left: 768, right: 768, top: 648, bottom: 648}",
                    ),
                    encoding="utf-8",
                )
                with Image.new("RGBA", (80, 60), (255, 255, 255, 0)) as image:
                    image.save(package / "artwork.png")
            elif count == 3:
                (package / "artwork.png").unlink()
            elif count == 4:
                with Image.new("RGBA", (1600, 1200), (255, 0, 0, 255)) as image:
                    image.save(package / "artwork.png")
            return next(actions)

        yield read

    diagnostic.run_decoration_diagnostic(
        config, debug_layout=True, backend_factory=lambda _: backend, input_factory=reader
    )
    captured = capsys.readouterr()
    assert captured.out.count("Presentation: 1 of 12") == 5
    assert "Literary output bounds: (192, 162, 1728, 918)" in captured.out
    assert "Literary output bounds: (384, 324, 1536, 756)" in captured.out
    assert captured.err.count("Cannot present decoration") == 2
    assert len(backend.images) == 6
    assert backend.images[0].tobytes() != backend.images[2].tobytes()
    assert backend.images[2].getpixel((384, 324)) == (127, 127, 127)
    assert backend.images[4].getpixel((320, 180)) == (0, 0, 255)
    assert backend.images[4].getpixel((384, 324)) == (0, 0, 127)
    assert backend.closed
    for image in backend.images:
        image.close()


def test_snapshot_preferences_qr_and_fully_revealed(workspace, monkeypatch):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    prepare = diagnostic.prepare_daily_images
    captured = []

    def record(snapshot, stages, *registries, **kwargs):
        captured.append((snapshot, stages))
        return prepare(snapshot, stages, *registries, **kwargs)

    monkeypatch.setattr(diagnostic, "prepare_daily_images", record)
    for variant in (0, 1):
        image, snapshot = diagnostic._render(configuration, "a-custom", resource.manifest, variant, False)
        assert snapshot.decoration == "a-custom"
        assert snapshot.font is None
        assert snapshot.background is None
        assert snapshot.text_color is None
        assert snapshot.decoration_color is None
        qr = render_qr_code(PRODUCTION_QR_PARAMETERS, image.size, resolve_qr_placement(image.size))
        try:
            left, top, _, _ = qr.geometry.bounds
            quiet_zone = qr.geometry.quiet_zone_pixels
            assert image.getpixel((left, top)) == (255, 255, 255)
            assert image.getpixel((left + quiet_zone, top + quiet_zone)) == (0, 0, 0)
        finally:
            qr.image.close()
        image.close()
    assert all(stages[0].quotation and stages[0].source and stages[0].attribution for _, stages in captured)


def test_existing_nonfatal_manifest_warnings_do_not_prevent_inspection(workspace, capsys):
    config, package = workspace
    manifest = package / "decoration.yaml"
    manifest.write_text(_MANIFEST + "future_field: value\n", encoding="utf-8")
    backends = {name: RecordingBackend() for name in ("window", "image-server")}

    @contextmanager
    def reader():
        def change():
            manifest.write_text(
                _MANIFEST.replace("tintable: true", "tintable: broken") + "future_field: value\n", encoding="utf-8"
            )
            return "r"

        keys = iter([change, lambda: "q"])
        yield lambda: next(keys)()

    diagnostic.run_decoration_diagnostic(
        config, backend_factory=lambda settings: backends[settings.type], input_factory=reader
    )
    assert "Cannot present decoration" in capsys.readouterr().err
    assert all(len(backend.images) == 1 for backend in backends.values())
    for backend in backends.values():
        for image in backend.images:
            image.close()


def test_reload_updates_font_face_background_and_colours(workspace):
    config, package = workspace
    before = diagnostic._load_configuration(config)
    manifest = before.decorations["a-custom"].manifest
    first, first_snapshot = diagnostic._render(before, "a-custom", manifest, 0, False)
    updated = (
        _MANIFEST.replace("font: lora", "font: alegreya")
        .replace("quotation: italic", "quotation: bold")
        .replace("background: none", "background: canvas")
        .replace("text_color: red", "text_color: black")
        .replace("decoration_color: blue", "decoration_color: red")
    )
    (package / "decoration.yaml").write_text(updated, encoding="utf-8")
    after = diagnostic._load_configuration(config)
    second, second_snapshot = diagnostic._render(after, "a-custom", manifest, 0, False)
    assert first_snapshot == second_snapshot
    assert first.tobytes() != second.tobytes()
    first.close()
    second.close()


@pytest.mark.parametrize(
    "mode", ["--once", "--demo=1", "--show-entry=x", "--test-qr", "--initialize", "--reset", "--purge"]
)
def test_cli_modes_are_mutually_exclusive(mode):
    with pytest.raises(SystemExit) as error:
        cli.main(["--test-decoration", "all", mode])
    assert error.value.code == 2


def test_noninteractive_input_rejected(workspace, monkeypatch):
    monkeypatch.setattr(diagnostic.sys.stdin, "isatty", lambda: False)
    with pytest.raises(application.ApplicationError, match="interactive terminal"):
        with diagnostic.single_key_input():
            pass


def test_empty_registry(workspace, monkeypatch):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    from dataclasses import replace

    monkeypatch.setattr(diagnostic, "_load_configuration", lambda _: replace(configuration, decorations={}))
    with pytest.raises(application.ApplicationError, match="no usable decorations"):
        diagnostic.run_decoration_diagnostic(config)


@pytest.mark.skipif(os.name != "posix", reason="POSIX terminal settings")
def test_terminal_settings_restored_after_exception(monkeypatch):
    import termios
    import tty

    calls = []
    monkeypatch.setattr(diagnostic.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(diagnostic.sys.stdin, "fileno", lambda: 10)
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: ["original"])
    monkeypatch.setattr(tty, "setcbreak", lambda fd: calls.append(("cbreak", fd)))
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, settings: calls.append(("restore", fd, settings)))
    with pytest.raises(RuntimeError, match="failure"):
        with diagnostic.single_key_input():
            raise RuntimeError("failure")
    assert calls == [("cbreak", 10), ("restore", 10, ["original"])]


def test_publication_failure_is_reported_and_resources_closed(workspace, capsys):
    config, _ = workspace

    class FailingBackend(RecordingBackend):
        def update(self, image):
            raise RuntimeError("display disconnected")

    backends = {"window": FailingBackend(), "image-server": RecordingBackend()}
    diagnostic.run_decoration_diagnostic(
        config, backend_factory=lambda settings: backends[settings.type], input_factory=input_keys([" ", "q"])
    )
    assert "display disconnected" in capsys.readouterr().err
    assert all(backend.closed for backend in backends.values())
    assert len(backends["image-server"].images) == 2
    for image in backends["image-server"].images:
        image.close()


def test_ctrl_c_cleans_up(workspace):
    config, _ = workspace
    backends = {name: RecordingBackend() for name in ("window", "image-server")}

    @contextmanager
    def reader():
        def interrupt():
            raise KeyboardInterrupt

        yield interrupt

    diagnostic.run_decoration_diagnostic(
        config, backend_factory=lambda settings: backends[settings.type], input_factory=reader
    )
    assert all(backend.closed for backend in backends.values())
    for backend in backends.values():
        for image in backend.images:
            image.close()


def test_diagnostic_state_wraps_and_keyboard_controls_match_actions():
    state = diagnostic.DiagnosticState(("a", "b"))
    assert diagnostic.transition_state(state, "previous-decoration").decoration == "b"
    assert diagnostic.transition_state(state, "next-decoration").decoration == "b"
    assert diagnostic.transition_state(state, "previous-quotation").quotation_index == 2
    assert diagnostic.transition_state(diagnostic.transition_state(state, "toggle-qr"), "toggle-background") == replace(
        state, qr_enabled=False, background_enabled=False
    )
    for key, action in (
        ("\x1b[A", "next-quotation"),
        ("\xe0K", "previous-decoration"),
        (" ", "next-decoration"),
        ("q", "toggle-qr"),
        ("\x1b[15~", "reload"),
    ):
        assert diagnostic._state_action(key) == action


@pytest.mark.parametrize(
    ("aspect", "size"),
    [("configured", (1920, 1080)), ("4:3", (1920, 1440)), ("16:9", (1920, 1080)), ("16:10", (1920, 1200))],
)
def test_aspect_output_geometry_and_screen_fit(workspace, aspect, size):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    assert diagnostic._with_aspect(configuration, aspect).output_size == size
    preview = diagnostic.preview_size_for_screen(size, (1366, 768))
    assert preview[0] <= 1326 and preview[1] <= 564
    assert preview[0] * size[1] == preview[1] * size[0] or preview == (1, 1)


def test_aspect_override_resolves_exact_geometry_for_other_configured_widths(workspace):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    configuration = replace(configuration, output_size=(1000, 750))
    assert diagnostic._with_aspect(configuration, "16:9").output_size == (1008, 567)
    assert diagnostic._with_aspect(configuration, "16:10").output_size == (1000, 625)


def test_geometry_initialization_inheritance_and_independent_inset_overrides(workspace):
    config, package = workspace
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    insets, qr, horizontal, vertical, inset_source, qr_source = diagnostic._decoration_geometry(configuration, resource)
    assert (insets.left, insets.right, insets.top, insets.bottom) == (384, 384, 324, 324)
    assert (horizontal.method, horizontal.offset) == ("right", 20)
    assert (vertical.method, vertical.offset) == ("bottom", 20)
    assert inset_source == "decoration" and qr_source == "default"
    assert qr == {}

    state = diagnostic.DiagnosticState(("a-custom",))
    state = diagnostic._set_geometry_override(state, "a-custom", inset=("left", 510))
    (package / "decoration.yaml").write_text(
        _MANIFEST.replace(
            "presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}",
            "presentation_insets: {left: 111, right: 222, top: 333, bottom: 444}",
        ),
        encoding="utf-8",
    )
    reloaded = diagnostic._load_configuration(config)
    insets, *_ = diagnostic._decoration_geometry(
        reloaded, reloaded.decorations["a-custom"], dict(state.geometry_overrides)["a-custom"]
    )
    assert (insets.left, insets.right, insets.top, insets.bottom) == (510, 222, 333, 444)
    assert reloaded.decorations["a-custom"].presentation_insets.left == 111

    inherited_manifest = _MANIFEST.replace("presentation_insets: {left: 384, right: 384, top: 324, bottom: 324}\n", "")
    (package / "decoration.yaml").write_text(inherited_manifest, encoding="utf-8")
    inherited = diagnostic._load_configuration(config)
    resolved, *_rest, source, _qr_source = diagnostic._decoration_geometry(inherited, inherited.decorations["a-custom"])
    assert (resolved.left, resolved.right, resolved.top, resolved.bottom) == (384, 384, 324, 324)
    assert source == "inherited"


def test_geometry_qr_methods_exclusivity_and_manifest_fragment(workspace):
    config, package = workspace
    (package / "decoration.yaml").write_text(
        _MANIFEST.replace("presentation_insets:", "qr_from_left: 35\nqr_from_top: 45\npresentation_insets:"),
        encoding="utf-8",
    )
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    state = diagnostic.DiagnosticState(("a-custom",))
    state = diagnostic._set_geometry_override(state, "a-custom", qr_horizontal=diagnostic._QRPosition("right", 51))
    state = diagnostic._set_geometry_override(state, "a-custom", qr_vertical=diagnostic._QRPosition("center"))
    overrides = dict(state.geometry_overrides)["a-custom"]
    insets, metadata, horizontal, vertical, _, _ = diagnostic._decoration_geometry(configuration, resource, overrides)
    assert (horizontal.method, horizontal.offset) == ("right", 51)
    assert vertical.method == "center"
    assert metadata == {"qr_from_right": 51, "qr_centered": "vertical"}
    placement = diagnostic.resolve_qr_placement(configuration.output_size, metadata)
    assert placement.working_bounds[0] == 3840 - 246 - 51
    fragment, _ = diagnostic._geometry_manifest_values(configuration, resource, overrides, configuration.output_size)
    parsed = yaml.safe_load(fragment)
    assert parsed == {
        "presentation_insets": {"left": 384, "right": 384, "top": 324, "bottom": 324},
        "qr_from_right": 51,
        "qr_centered": "vertical",
    }

    state = diagnostic._set_geometry_override(state, "a-custom", qr_horizontal=diagnostic._QRPosition("center"))
    overrides = dict(state.geometry_overrides)["a-custom"]
    _, metadata, horizontal, vertical, _, _ = diagnostic._decoration_geometry(configuration, resource, overrides)
    assert horizontal.method == "center"
    assert (vertical.method, vertical.offset) == ("bottom", 20)
    assert metadata == {"qr_centered": "horizontal", "qr_from_bottom": 20}
    assert diagnostic._reset_geometry_overrides(state, "a-custom").geometry_overrides == ()


def test_geometry_override_rendering_aspect_and_debug_bounds(workspace):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    state = diagnostic.DiagnosticState(("a-custom",), aspect_ratio="4:3")
    state = diagnostic._set_geometry_override(state, "a-custom", inset=("left", 500))
    state = diagnostic._set_geometry_override(state, "a-custom", qr_horizontal=diagnostic._QRPosition("left", 60))
    overrides = dict(state.geometry_overrides)["a-custom"]
    details = []
    image, _ = diagnostic._render(
        configuration,
        "a-custom",
        resource.manifest,
        0,
        True,
        aspect_ratio=state.aspect_ratio,
        diagnostics_out=details,
        geometry_overrides=overrides,
    )
    try:
        assert details[0].geometry.working_region == (500, 324, 2816, 2076)
        assert details[0].qr_placement.working_bounds[0] == 60
        assert details[0].qr_placement.image_size == image.size == (1920, 1440)
        assert image.getpixel((details[0].geometry.output_region[0], details[0].geometry.output_region[1])) != (
            255,
            255,
            255,
        )
    finally:
        image.close()


def test_geometry_overrides_are_per_decoration_and_reset_independently():
    state = diagnostic.DiagnosticState(("a", "b"))
    state = diagnostic._set_geometry_override(state, "a", inset=("left", 100))
    state = diagnostic._set_geometry_override(state, "b", inset=("right", 200))
    assert dict(state.geometry_overrides)["a"].presentation_insets == (("left", 100),)
    assert dict(state.geometry_overrides)["b"].presentation_insets == (("right", 200),)
    reset_a = diagnostic._reset_geometry_overrides(state, "a")
    assert set(dict(reset_a.geometry_overrides)) == {"b"}


def test_reload_preserves_valid_selection_and_overrides(workspace):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    identifiers = diagnostic._configuration_decoration_ids(configuration)
    state = diagnostic.DiagnosticState(
        identifiers,
        decoration_index=identifiers.index("a-custom"),
        quotation_index=2,
        aspect_ratio="16:10",
        qr_enabled=False,
        background_enabled=False,
        tinting_enabled=False,
        debug_layout=True,
    )
    preserved, message = diagnostic._reconcile_state(state, configuration)
    assert message is None
    assert preserved == state
    remaining = replace(
        configuration,
        decorations={key: value for key, value in configuration.decorations.items() if key != "a-custom"},
    )
    recovered, message = diagnostic._reconcile_state(state, remaining)
    assert recovered.decoration == identifiers[1]
    assert "a-custom" in message
    assert recovered.quotation_index == 2
    assert recovered.aspect_ratio == "16:10"
    assert not recovered.qr_enabled and not recovered.background_enabled and not recovered.tinting_enabled
    assert recovered.debug_layout


def test_cli_decoration_preview_options_are_passed_as_initial_state(workspace, monkeypatch):
    config, _ = workspace
    observed = {}
    monkeypatch.setattr(
        cli,
        "run_decoration_diagnostic",
        lambda config_path, **options: observed.update(config_path=config_path, **options),
    )
    assert (
        cli.main(
            [
                "--config",
                str(config),
                "--test-decoration",
                "all",
                "--test-aspect",
                "4:3",
                "--test-quotation",
                "medium",
                "--no-qr",
                "--no-background",
                "--no-tinting",
                "--debug-layout",
            ]
        )
        == 0
    )
    assert observed["selection"] == "all"
    assert observed["aspect_ratio"] == "4:3"
    assert observed["quotation"] == "medium"
    assert observed["qr_enabled"] is False
    assert observed["background_enabled"] is False
    assert observed["tinting_enabled"] is False
    assert observed["debug_layout"] is True


def test_cli_headless_png_export_uses_pipeline_without_gui_or_state(workspace, monkeypatch, capsys):
    config, _ = workspace
    output_one = config.parent / "new" / "nested" / "preview.png"
    output_two = config.parent / "other" / "preview.png"
    monkeypatch.setattr(
        diagnostic,
        "_run_tk_preview",
        lambda *_: pytest.fail("headless output must not initialize Tk"),
    )
    arguments = [
        "--config",
        str(config),
        "--test-decoration",
        "a-custom",
        "--test-output",
        str(output_one),
        "--test-aspect",
        "4:3",
        "--test-quotation",
        "medium",
        "--no-qr",
        "--no-background",
        "--no-tinting",
        "--debug-layout",
    ]
    assert cli.main(arguments) == 0
    with Image.open(output_one) as first:
        assert first.format == "PNG"
        assert first.size == (1920, 1440)
        first_bytes = output_one.read_bytes()

    second_arguments = list(arguments)
    second_arguments[second_arguments.index(str(output_one))] = str(output_two)
    assert cli.main(second_arguments) == 0
    assert output_two.read_bytes() == first_bytes
    assert "Diagnostic PNG saved to" in capsys.readouterr().out
    assert not (config.parent / "state.json").exists()
    assert not (config.parent / "global-history.jsonl").exists()
    assert not (config.parent / "artifacts").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--test-output", "preview.png"],
        ["--test-decoration", "all", "--test-output", "preview.png"],
    ],
)
def test_test_output_requires_one_decoration_id(arguments):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


@pytest.mark.parametrize("mode", ["--once", "--test-qr"])
def test_decoration_preview_rejects_other_modes(mode):
    with pytest.raises(SystemExit) as error:
        cli.main(["--test-decoration", "all", mode])
    assert error.value.code == 2


def test_test_output_reports_unwritable_parent(workspace):
    config, _ = workspace
    parent = config.parent / "not-a-directory"
    parent.write_text("file", encoding="utf-8")
    state = diagnostic.DiagnosticState(("a-custom",))
    with pytest.raises(application.ApplicationError, match="cannot save diagnostic PNG"):
        diagnostic.export_decoration_png(config, state, parent / "preview.png")


def test_test_output_reports_render_failure(workspace, monkeypatch):
    config, _ = workspace
    monkeypatch.setattr(
        diagnostic,
        "_render_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(application.ApplicationError("render failed")),
    )
    with pytest.raises(application.ApplicationError, match="render failed"):
        diagnostic.export_decoration_png(
            config,
            diagnostic.DiagnosticState(("a-custom",)),
            config.parent / "preview.png",
        )


@pytest.mark.parametrize("option", ["--test-aspect", "--test-quotation", "--no-qr", "--no-background", "--no-tinting"])
def test_diagnostic_cli_options_are_rejected_outside_mode(option):
    value = "16:9" if option == "--test-aspect" else "medium"
    arguments = [option, value] if option in {"--test-aspect", "--test-quotation"} else [option]
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


def test_obsolete_decoration_cli_option_is_removed():
    with pytest.raises(SystemExit) as error:
        cli.main(["--test-decorations"])
    assert error.value.code == 2


def test_invalid_decoration_selection_names_available_choices(workspace):
    config, _ = workspace
    with pytest.raises(application.ApplicationError, match="available selections: all, a-custom"):
        diagnostic.run_decoration_diagnostic(config, selection="missing", preview_factory=lambda *_: None)


def test_individual_selection_stays_targeted_on_start(workspace):
    config, _ = workspace
    states = []
    diagnostic.run_decoration_diagnostic(
        config, selection="a-custom", preview_factory=lambda _config, state: states.append(state)
    )
    assert "a-custom" in states[0].decoration_ids
    assert states[0].decoration == "a-custom"
    assert not states[0].all_decorations


def test_preview_overrides_use_shared_preparation_pipeline(workspace):
    config, package = workspace
    config.write_text(
        _CONFIG.replace("default: [none]\n  decorations:", "default: [canvas]\n  decorations:"),
        encoding="utf-8",
    )
    manifest_path = package / "decoration.yaml"
    manifest_path.write_text(_MANIFEST.replace("background: none\n", ""), encoding="utf-8")
    with Image.new("RGBA", (40, 20), (0, 0, 255, 255)) as image:
        image.save(package / "artwork.png")
    configuration = diagnostic._load_configuration(config)
    details = []
    image, _ = diagnostic._render(
        configuration,
        "a-custom",
        configuration.decorations["a-custom"].manifest,
        0,
        False,
        aspect_ratio="4:3",
        qr_enabled=False,
        background_enabled=False,
        tinting_enabled=False,
        diagnostics_out=details,
    )
    assert image.size == (1920, 1440)
    assert image.getpixel((100, 100)) == (255, 255, 255)
    assert image.getpixel((100, 720)) == (0, 0, 0)
    assert details[0].qr_placement is None
    assert "disabled" in details[0].qr_unavailable_reason
    image.close()


def test_decoration_tint_override_is_black_only_for_tintable_layers(workspace):
    config, package = workspace
    configuration = diagnostic._load_configuration(config)
    manifest = package / "decoration.yaml"
    with Image.new("RGBA", (80, 60), (0, 0, 255, 255)) as image:
        image.save(package / "artwork.png")
    untinted = manifest.read_text(encoding="utf-8").replace("method: contain", "method: contain\n    tintable: false")
    manifest.write_text(untinted, encoding="utf-8")
    configuration = diagnostic._load_configuration(config)
    image, _ = diagnostic._render(
        configuration,
        "a-custom",
        configuration.decorations["a-custom"].manifest,
        0,
        False,
        tinting_enabled=False,
    )
    assert image.getpixel((960, 540)) == (0, 0, 255)
    image.close()


def test_qr_toggle_uses_resolved_availability_for_conditional_layers(workspace):
    config, package = workspace
    manifest = package / "decoration.yaml"
    manifest.write_text(_MANIFEST.replace("method: contain", "method: contain\n    condition: qr"), encoding="utf-8")
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    details_without_qr = []
    image_without_qr, _ = diagnostic._render(
        configuration, "a-custom", resource.manifest, 0, False, qr_enabled=False, diagnostics_out=details_without_qr
    )
    assert details_without_qr[0].qr_placement is None
    assert details_without_qr[0].active_layers == ()
    details_with_qr = []
    image_with_qr, _ = diagnostic._render(
        configuration, "a-custom", resource.manifest, 0, False, qr_enabled=True, diagnostics_out=details_with_qr
    )
    assert details_with_qr[0].qr_placement is not None
    assert details_with_qr[0].active_layers == (resource.layers[0],)
    image_without_qr.close()
    image_with_qr.close()


def test_qr_toggle_does_not_override_disabled_configuration(workspace):
    config, _ = workspace
    configuration = replace(diagnostic._load_configuration(config), qr_enabled=False)
    resource = configuration.decorations["a-custom"]
    details = []
    image, _ = diagnostic._render(
        configuration, "a-custom", resource.manifest, 0, False, qr_enabled=True, diagnostics_out=details
    )
    assert details[0].qr_placement is None
    assert details[0].qr_unavailable_reason == "QR generation is disabled by configuration"
    image.close()


@pytest.mark.parametrize(
    ("manifest_update", "reason"),
    [
        ("qr_ready: false\n", "not marked qr_ready"),
        ("qr_from_left: 100000\n", "extends outside"),
    ],
)
def test_unavailable_qr_reports_the_resolver_reason(workspace, manifest_update, reason):
    config, package = workspace
    manifest_path = package / "decoration.yaml"
    manifest_path.write_text(_MANIFEST + manifest_update, encoding="utf-8")
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    details = []
    image, _ = diagnostic._render(
        configuration, "a-custom", resource.manifest, 0, False, qr_enabled=True, diagnostics_out=details
    )
    assert details[0].qr_placement is None
    assert reason in details[0].qr_unavailable_reason
    image.close()


def test_nine_slice_guides_reuse_boundaries_and_deduplicate_sets(workspace):
    config, package = workspace
    first_layer = """\
  - image: artwork.png
    method: nine-slice
    slices: {left: 10, right: 10, top: 10, bottom: 10}
"""
    second_layer = """\
  - image: artwork.png
    method: nine-slice
    slices: {left: 10, right: 10, top: 10, bottom: 10}
"""
    third_layer = """\
  - image: artwork.png
    method: nine-slice
    slices: {left: 12, right: 12, top: 8, bottom: 8}
"""
    layers = "layers:\n" + first_layer + second_layer + third_layer
    manifest_text = _MANIFEST.replace("layers:\n  - image: artwork.png\n    method: contain\n", layers)
    (package / "decoration.yaml").write_text(manifest_text, encoding="utf-8")
    configuration = diagnostic._load_configuration(config)
    details = []
    image, _ = diagnostic._render(
        configuration,
        "a-custom",
        configuration.decorations["a-custom"].manifest,
        0,
        True,
        diagnostics_out=details,
    )
    resolved = details[0]
    assert len(resolved.nine_slice_guides) == 3
    groups = diagnostic._guide_groups(resolved)
    assert len(groups) == 2
    assert diagnostic._guide_color(0, 2) != diagnostic._guide_color(1, 2)
    assert resolved.nine_slice_guides[0].x_bounds == (0, 400, 3440, 3840)
    assert resolved.nine_slice_guides[0].y_bounds == (0, 400, 1760, 2160)
    image.close()


def test_gui_runner_receives_same_keyboard_and_toolbar_state_transitions(workspace):
    config, _ = workspace
    captured = []

    def fake_preview(config_path, state):
        state = diagnostic.transition_state(state, diagnostic._state_action("Right"))
        state = diagnostic.transition_state(state, diagnostic._state_action("q"))
        captured.append((config_path, state))

    diagnostic.run_decoration_diagnostic(config, selection="all", preview_factory=fake_preview)
    assert captured[0][0] == config
    assert captured[0][1].decoration_index == 1
    assert not captured[0][1].qr_enabled


def test_aspect_cycle_order_and_centered_preview_window():
    state = diagnostic.DiagnosticState(("a",), aspect_ratio="4:3")
    assert diagnostic.normalize_key("a") == "a"
    assert diagnostic._state_action("a") == "next-aspect"
    state = diagnostic.transition_state(state, "next-aspect")
    assert state.aspect_ratio == "16:9"
    state = diagnostic.transition_state(state, "next-aspect")
    assert state.aspect_ratio == "16:10"
    state = diagnostic.transition_state(state, "next-aspect")
    assert state.aspect_ratio == "4:3"

    preview, (width, height, left, top) = diagnostic.preview_window_layout((1920, 1440), (1366, 768), (900, 32))
    assert preview[0] * 3 == preview[1] * 4
    assert width >= preview[0] + 16
    assert height >= preview[1]
    assert left == (1366 - width) // 2
    assert top == (768 - height) // 2
    assert left + width <= 1366 and top + height <= 768
    expanded_preview, (expanded_width, expanded_height, expanded_left, expanded_top) = diagnostic.preview_window_layout(
        (1920, 1440),
        (1366, 768),
        (900, 32),
        status_height=100,
        geometry_height=130,
        geometry_width=1040,
    )
    assert expanded_preview[0] * 3 == expanded_preview[1] * 4
    assert expanded_preview[1] < preview[1]
    assert expanded_left + expanded_width <= 1366
    assert expanded_top + expanded_height <= 768
    assert expanded_width >= 1040


def test_debug_toggle_regenerates_clean_presentation(workspace):
    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    resource = configuration.decorations["a-custom"]
    clean_before, _ = diagnostic._render(configuration, "a-custom", resource.manifest, 0, False, qr_enabled=False)
    annotated, _ = diagnostic._render(configuration, "a-custom", resource.manifest, 0, True, qr_enabled=False)
    clean_after, _ = diagnostic._render(configuration, "a-custom", resource.manifest, 0, False, qr_enabled=False)
    assert clean_before.tobytes() == clean_after.tobytes()
    assert clean_before.tobytes() != annotated.tobytes()
    clean_before.close()
    annotated.close()
    clean_after.close()


def test_tk_toolbar_keyboard_dispatch_and_close_lifecycle(workspace, monkeypatch):
    from threading import Event

    config, _ = workspace
    configuration = diagnostic._load_configuration(config)
    roots = []
    buttons = []
    comboboxes = []
    entries = []
    submitted_states = []
    displayed_states = []
    photo_count = [0]
    initial_render_started = Event()
    release_initial_render = Event()

    class Widget:
        def __init__(self, parent=None, **options):
            self.options = options
            self.command = options.get("command")
            self.bindings = {}
            self.destroyed = False
            self.children = []
            if parent is not None and hasattr(parent, "children"):
                parent.children.append(self)

        def pack(self, **_options):
            pass

        def pack_forget(self):
            pass

        def bind(self, event, callback):
            self.bindings[event] = callback

        def configure(self, **options):
            self.options.update(options)

        def winfo_reqwidth(self):
            return max(40, len(str(self.options.get("text", ""))) * 8 + 20)

        def winfo_reqheight(self):
            return 32

    class Root:
        def __init__(self):
            self.callbacks = []
            self.bindings = {}
            self.protocols = {}
            self.destroyed = False
            self.closing = False
            self.geometries = []
            roots.append(self)

        def title(self, _value):
            pass

        def configure(self, **_options):
            pass

        def geometry(self, _value):
            self.geometries.append(_value)

        def update_idletasks(self):
            pass

        def winfo_screenwidth(self):
            return 1366

        def winfo_screenheight(self):
            return 768

        def bind(self, event, callback):
            self.bindings[event] = callback

        def protocol(self, name, callback):
            self.protocols[name] = callback

        def after(self, _milliseconds, callback):
            self.callbacks.append(callback)

        def destroy(self):
            self.destroyed = True
            self.closing = True

        def mainloop(self):
            deadline = time.monotonic() + 10
            burst_dispatched = False
            keyboard_dispatched = False
            geometry_dispatched = False
            geometry_edit_dispatched = False
            aspect_dispatched = False
            picker_dispatched = False
            mouse_dispatched = False
            while not self.closing:
                if self.callbacks:
                    self.callbacks.pop(0)()
                else:
                    time.sleep(0.005)
                if initial_render_started.is_set() and not burst_dispatched:
                    self.bindings["<KeyPress>"](SimpleNamespace(keysym="Right", char=""))
                    self.bindings["<KeyPress>"](SimpleNamespace(keysym="b", char="b"))
                    release_initial_render.set()
                    burst_dispatched = True
                elif photo_count[0] == 1 and not geometry_dispatched:
                    next(button for button in buttons if button.options["text"] == "Geometry ▸").command()
                    geometry_dispatched = True
                elif photo_count[0] == 2 and not geometry_edit_dispatched:
                    left_entry = entries[0]
                    left_entry.options["textvariable"].set("")
                    left_entry.bindings["<KeyRelease>"](None)
                    assert (
                        next(button for button in buttons if button.options["text"] == "Copy values").options["state"]
                        == "disabled"
                    )
                    left_entry.options["textvariable"].set("500")
                    left_entry.bindings["<KeyRelease>"](None)
                    left_entry.bindings["<Return>"](None)
                    geometry_edit_dispatched = True
                elif photo_count[0] == 3 and not keyboard_dispatched:
                    self.bindings["<KeyPress>"](SimpleNamespace(keysym="Right", char=""))
                    keyboard_dispatched = True
                elif photo_count[0] == 4 and not aspect_dispatched:
                    self.bindings["<KeyPress>"](SimpleNamespace(keysym="a", char="a"))
                    aspect_dispatched = True
                elif photo_count[0] == 5 and not picker_dispatched:
                    picker = next(combo for combo in comboboxes if "a-custom" in combo.options.get("values", ()))
                    picker.options["textvariable"].set("a-custom")
                    picker.bindings["<<ComboboxSelected>>"](None)
                    picker_dispatched = True
                elif photo_count[0] == 6 and not mouse_dispatched:
                    next(button for button in buttons if button.options["text"] == "QR ✓").command()
                    mouse_dispatched = True
                elif photo_count[0] == 7:
                    self.protocols["WM_DELETE_WINDOW"]()
                if time.monotonic() > deadline:
                    raise TimeoutError("preview did not process its render/close sequence")

    class Variable:
        def __init__(self, value=""):
            self.value = value

        def set(self, value):
            self.value = value

        def get(self):
            return self.value

    tkinter = ModuleType("tkinter")
    tkinter.Tk = Root
    tkinter.Frame = Widget
    tkinter.Label = Widget

    def create_entry(parent, **options):
        entry = Widget(parent, **options)
        entries.append(entry)
        return entry

    tkinter.Entry = create_entry
    tkinter.StringVar = Variable

    def create_button(parent, **options):
        button = Widget(parent, **options)
        buttons.append(button)
        return button

    tkinter.Button = create_button
    ttk = ModuleType("tkinter.ttk")

    def create_combobox(parent, **options):
        combobox = Widget(parent, **options)
        comboboxes.append(combobox)
        return combobox

    ttk.Combobox = create_combobox
    tkinter.ttk = ttk
    image_tk = ModuleType("PIL.ImageTk")

    class PhotoImage:
        def __init__(self, image):
            photo_count[0] += 1
            self.size = image.size

    image_tk.PhotoImage = PhotoImage
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "PIL.ImageTk", image_tk)

    def render_request(_config_file, state, _configuration, reload_configuration=False):
        submitted_states.append(state)
        if len(submitted_states) == 1:
            initial_render_started.set()
            assert release_initial_render.wait(5)
        current_configuration = diagnostic._with_aspect(configuration, state.aspect_ratio)
        geometry = diagnostic.resolve_presentation_geometry(
            current_configuration.output_size, current_configuration.presentation_insets
        )
        return diagnostic._RenderedPreview(
            Image.new("RGB", current_configuration.output_size, "white"),
            None,
            diagnostic.PreparationDiagnostics(geometry, None, "disabled", (), ()),
            current_configuration,
            state,
        )

    monkeypatch.setattr(diagnostic, "_render_request", render_request)
    monkeypatch.setattr(
        diagnostic,
        "_diagnostic_status",
        lambda state, *_args: displayed_states.append(state) or "preview",
    )
    initial = diagnostic.DiagnosticState(diagnostic._configuration_decoration_ids(configuration), aspect_ratio="16:9")
    diagnostic._run_tk_preview(config, initial)
    assert [state.aspect_ratio for state in submitted_states] == [
        "16:9",
        "16:9",
        "16:9",
        "16:9",
        "16:10",
        "16:10",
        "16:10",
    ]
    assert submitted_states[1].decoration == initial.decoration_ids[1]
    assert not submitted_states[1].background_enabled
    assert displayed_states[0].decoration == initial.decoration_ids[1]
    assert not displayed_states[0].background_enabled
    assert submitted_states[5].decoration == "a-custom"
    assert dict(submitted_states[5].geometry_overrides).get("a-custom") is None
    assert submitted_states[-1].qr_enabled is False
    assert any(
        dict(state.geometry_overrides).get(state.decoration) is not None
        and dict(state.geometry_overrides)[state.decoration].presentation_insets == (("left", 500),)
        for state in submitted_states
    )
    assert roots[0].destroyed
    assert len(roots[0].geometries) >= 2

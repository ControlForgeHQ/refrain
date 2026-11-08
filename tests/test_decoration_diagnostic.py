from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from PIL import Image

import refrain.__main__ as cli
import refrain.application as application
import refrain.decoration_diagnostic as diagnostic
from refrain.qr import PRODUCTION_QR_PARAMETERS, render_qr_code

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
image: artwork.png
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
        qr = render_qr_code(PRODUCTION_QR_PARAMETERS, image.size)
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
        cli.main(["--test-decorations", mode])
    assert error.value.code == 2


def test_noninteractive_input_rejected(workspace, monkeypatch):
    config, _ = workspace
    monkeypatch.setattr(diagnostic.sys.stdin, "isatty", lambda: False)
    with pytest.raises(application.ApplicationError, match="interactive terminal"):
        diagnostic.run_decoration_diagnostic(config)


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

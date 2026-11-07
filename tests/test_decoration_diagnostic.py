from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from PIL import Image

import refrain.__main__ as cli
import refrain.application as application
import refrain.decoration_diagnostic as diagnostic

_CONFIG = """\
display:
  backends:
    - type: window
    - type: image-server
layout:
  presentation_region: {x: 0.1, y: 0.15, width: 0.8, height: 0.7}
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
presentation_region: {x: 0.1, y: 0.15, width: 0.8, height: 0.7}
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
    ids = [snapshot.decoration_identifier for snapshot in snapshots]
    assert ids == ["a-custom", "a-custom", "a-custom", "top-bottom-borders", "a-custom", "a-custom", "a-custom"]
    assert snapshots[0].quotation_text == snapshots[2].quotation_text == snapshots[4].quotation_text
    assert snapshots[0].quotation_text != snapshots[1].quotation_text
    assert all(
        snapshot.presentation_metadata["source"] and snapshot.presentation_metadata["attribution"]
        for snapshot in snapshots
    )
    output = capsys.readouterr().out
    assert "Presentation: 1 of 12" in output
    assert "Quotation: SHORT" in output and "Quotation: LONG" in output
    assert "Presentation region:" in output
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
                manifest.write_text(_MANIFEST.replace("x: 0.1", "x: 0.2"), encoding="utf-8")
                with Image.new("RGBA", (80, 60), (255, 255, 255, 0)) as image:
                    image.save(package / "artwork.png")
            elif count == 3:
                (package / "artwork.png").unlink()
            elif count == 4:
                with Image.new("RGBA", (80, 60), (255, 0, 0, 255)) as image:
                    image.save(package / "artwork.png")
            return next(actions)

        yield read

    diagnostic.run_decoration_diagnostic(
        config, debug_layout=True, backend_factory=lambda _: backend, input_factory=reader
    )
    captured = capsys.readouterr()
    assert captured.out.count("Presentation: 1 of 12") == 5
    assert "x=0.1" in captured.out and "x=0.2" in captured.out
    assert captured.err.count("Cannot present decoration") == 2
    assert len(backend.images) == 6
    assert backend.images[0].tobytes() != backend.images[2].tobytes()
    assert backend.images[2].getpixel((320, 180)) == (127, 127, 127)
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
        assert snapshot.presentation_metadata["font_faces"]["quotation"] == "italic"
        assert snapshot.presentation_metadata["text_color_rgb"] == (255, 0, 0)
        assert snapshot.presentation_metadata["decoration_color_rgb"] == (0, 0, 255)
        assert snapshot.background_identifier == "none"
        assert snapshot.layout["presentation_region"]["x"] == 0.1
        assert snapshot.presentation_metadata["qr_code"]
        assert image.getpixel((1437, 1037)) == (255, 255, 255)
        assert image.getpixel((1449, 1049)) == (0, 0, 0)
        image.close()
    assert all(stages[0].quotation and stages[0].source and stages[0].attribution for _, stages in captured)


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

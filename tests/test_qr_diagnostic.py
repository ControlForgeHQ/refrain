from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import qrcode
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

import refrain.__main__ as cli
import refrain.application as application
from refrain import ApplicationError
from refrain.qr_diagnostic import (
    QRCalibrationError,
    QRCalibrationParameters,
    create_qr_calibration_image,
)

_ERROR_LEVELS = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}
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


class RecordingBackend:
    def __init__(self) -> None:
        self.images: list[Image.Image] = []
        self.closed = False

    def update(self, image: Image.Image) -> None:
        self.images.append(image.copy())

    def close(self) -> None:
        self.closed = True


def create_config(directory: Path, *, multiple_backends: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "config.yaml"
    text = _CONFIG
    if multiple_backends:
        text = text.replace('    - type: "window"', '    - type: "window"\n    - type: "image-server"')
    config.write_text(text, encoding="utf-8")
    (directory / "content").mkdir()
    return config


@pytest.mark.parametrize("level", ["L", "M", "Q", "H"])
@pytest.mark.parametrize("version", [None, 4])
def test_qr_generation_preserves_error_correction_and_exact_module_pixels(level: str, version: int | None) -> None:
    parameters = QRCalibrationParameters(
        payload="pixel grid", error_correction=level, version=version, module_size=3, quiet_zone=2
    )
    result = create_qr_calibration_image(parameters)
    try:
        expected = qrcode.QRCode(
            version=version,
            error_correction=_ERROR_LEVELS[level],
            box_size=1,
            border=0,
        )
        expected.add_data(parameters.payload.encode("utf-8"), optimize=0)
        expected.make(fit=version is None)
        geometry = result.geometry
        assert geometry.version == expected.version
        assert geometry.symbol_modules == expected.modules_count
        assert result.image.mode == "RGB"
        assert result.image.size == (1920, 1080)
        assert {color for _, color in result.image.getcolors(maxcolors=3)} <= {(0, 0, 0), (255, 255, 255)}

        symbol_left = geometry.bounds[0] + geometry.quiet_zone_pixels
        symbol_top = geometry.bounds[1] + geometry.quiet_zone_pixels
        for row_index, row in enumerate(expected.modules):
            for column_index, dark in enumerate(row):
                box = (
                    symbol_left + column_index * parameters.module_size,
                    symbol_top + row_index * parameters.module_size,
                    symbol_left + (column_index + 1) * parameters.module_size,
                    symbol_top + (row_index + 1) * parameters.module_size,
                )
                expected_pixel = (0, 0, 0) if dark else (255, 255, 255)
                with result.image.crop(box) as module:
                    assert module.getcolors() == [(parameters.module_size**2, expected_pixel)]
        quiet = geometry.quiet_zone_pixels
        left, top, right, bottom = geometry.bounds
        with result.image.crop((left, top, right + 1, top + quiet)) as top_quiet_zone:
            assert top_quiet_zone.getcolors() == [((right - left + 1) * quiet, (255, 255, 255))]
        with result.image.crop((left, top, left + quiet, bottom + 1)) as left_quiet_zone:
            assert left_quiet_zone.getcolors() == [(quiet * (bottom - top + 1), (255, 255, 255))]
        with result.image.crop((left, bottom - quiet + 1, right + 1, bottom + 1)) as bottom_quiet_zone:
            assert bottom_quiet_zone.getcolors() == [((right - left + 1) * quiet, (255, 255, 255))]
        with result.image.crop((right - quiet + 1, top, right + 1, bottom + 1)) as right_quiet_zone:
            assert right_quiet_zone.getcolors() == [(quiet * (bottom - top + 1), (255, 255, 255))]
    finally:
        result.image.close()


def test_qr_version_increases_for_larger_payload() -> None:
    short = create_qr_calibration_image(QRCalibrationParameters(payload="short"))
    long = create_qr_calibration_image(QRCalibrationParameters(payload="a" * 100))
    try:
        assert long.geometry.version > short.geometry.version
    finally:
        short.image.close()
        long.image.close()


@pytest.mark.parametrize(("version", "payload"), [(1, "x"), (40, "x"), (4, "short")])
def test_fixed_qr_versions_are_not_changed(version: int, payload: str) -> None:
    result = create_qr_calibration_image(QRCalibrationParameters(payload=payload, version=version))
    try:
        assert result.geometry.version == version
        assert result.geometry.symbol_modules == 17 + 4 * version
        assert result.geometry.footprint_size == ((17 + 4 * version + 8) * result.geometry.module_size,) * 2
    finally:
        result.image.close()


def test_fixed_qr_version_has_constant_footprint_for_different_payloads() -> None:
    short = create_qr_calibration_image(QRCalibrationParameters(payload="x", version=4))
    longer = create_qr_calibration_image(QRCalibrationParameters(payload="a" * 60, version=4))
    try:
        assert short.geometry.footprint_size == longer.geometry.footprint_size
        assert short.geometry.symbol_modules == longer.geometry.symbol_modules == 33
    finally:
        short.image.close()
        longer.image.close()


def test_default_and_configured_geometry_uses_complete_footprint() -> None:
    default = create_qr_calibration_image()
    configured = create_qr_calibration_image(
        QRCalibrationParameters(
            version=4,
            module_size=3,
            quiet_zone=1,
            right_offset=17,
            bottom_offset=9,
        )
    )
    try:
        assert default.geometry.footprint_size == (
            (default.geometry.symbol_modules + 8) * 4,
            (default.geometry.symbol_modules + 8) * 4,
        )
        assert default.geometry.bounds[2] == default.geometry.image_size[0] - 40 - 1
        assert default.geometry.bounds[3] == default.geometry.image_size[1] - 40 - 1
        assert configured.geometry.quiet_zone_pixels == 3
        assert configured.geometry.bounds[2] == configured.geometry.image_size[0] - 17 - 1
        assert configured.geometry.bounds[3] == configured.geometry.image_size[1] - 9 - 1
    finally:
        default.image.close()
        configured.image.close()


def test_zero_offsets_and_exact_fit_boundary() -> None:
    exact = create_qr_calibration_image(
        QRCalibrationParameters(
            payload="https://example.com/", module_size=48, quiet_zone=0, right_offset=0, bottom_offset=0
        ),
        output_size=(1600, 1200),
    )
    try:
        assert exact.geometry.version == 2
        assert exact.geometry.footprint_size == (1200, 1200)
        assert exact.geometry.bounds == (400, 0, 1599, 1199)
    finally:
        exact.image.close()

    with pytest.raises(QRCalibrationError, match=r"1225 x 1225.*available.*1600 x 1200"):
        create_qr_calibration_image(
            QRCalibrationParameters(
                payload="https://example.com/", module_size=49, quiet_zone=0, right_offset=0, bottom_offset=0
            ),
            output_size=(1600, 1200),
        )
    with pytest.raises(QRCalibrationError, match=r"1239 x 1239.*available.*1600 x 1200"):
        create_qr_calibration_image(
            QRCalibrationParameters(version=40, module_size=7, quiet_zone=0, right_offset=0, bottom_offset=0),
            output_size=(1600, 1200),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("payload", "", "nonempty"),
        ("payload", "\ud800", "UTF-8"),
        ("error_correction", "X", "L, M, Q, or H"),
        ("version", 0, "1 through 40"),
        ("version", -1, "1 through 40"),
        ("version", 41, "1 through 40"),
        ("version", 1.5, "1 through 40"),
        ("version", True, "1 through 40"),
        ("version", "4", "1 through 40"),
        ("module_size", 0, "positive integer"),
        ("module_size", True, "integer"),
        ("quiet_zone", -1, "nonnegative integer"),
        ("right_offset", -1, "nonnegative integers"),
        ("bottom_offset", 1.5, "integer"),
    ],
)
def test_invalid_qr_parameters_are_rejected(field: str, value: object, message: str) -> None:
    parameters = replace(QRCalibrationParameters(), **{field: value})
    with pytest.raises(QRCalibrationError, match=message):
        create_qr_calibration_image(parameters)


def test_payload_larger_than_supported_qr_capacity_is_actionable() -> None:
    with pytest.raises(QRCalibrationError, match="too large.*shorten the payload"):
        create_qr_calibration_image(QRCalibrationParameters(payload="x" * 3000))


def test_fixed_qr_version_capacity_error_is_actionable() -> None:
    with pytest.raises(
        QRCalibrationError,
        match=r"available capacity.*version 1.*error-correction level M.*increase the version.*shorten the payload",
    ):
        create_qr_calibration_image(QRCalibrationParameters(payload="x" * 100, version=1))


def test_cli_defaults_and_explicit_parameters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "resolve_application_paths",
        lambda: SimpleNamespace(config_file=config),
    )
    observed: list[tuple[Path, QRCalibrationParameters]] = []
    monkeypatch.setattr(
        cli,
        "run_test_qr",
        lambda path, parameters: observed.append((path, parameters)) or (tmp_path / "result.png", None),
    )

    assert cli.main(["--test-qr"]) == 0
    assert observed[-1] == (config, QRCalibrationParameters())
    assert cli.main(["--test-qr", "--qr-version", "auto"]) == 0
    assert observed[-1] == (config, QRCalibrationParameters())
    assert (
        cli.main(
            [
                "--test-qr",
                "--qr-payload",
                "https://example.com/calibration",
                "--qr-version",
                "4",
                "--qr-error-correction",
                "H",
                "--qr-module-size",
                "5",
                "--qr-quiet-zone",
                "2",
                "--qr-right-offset",
                "0",
                "--qr-bottom-offset",
                "7",
            ]
        )
        == 0
    )
    assert observed[-1][1] == QRCalibrationParameters(
        payload="https://example.com/calibration",
        error_correction="H",
        version=4,
        module_size=5,
        quiet_zone=2,
        right_offset=0,
        bottom_offset=7,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--qr-payload", "value"],
        ["--qr-version", "auto"],
        ["--qr-error-correction", "H"],
        ["--qr-module-size", "5"],
        ["--qr-quiet-zone", "2"],
        ["--qr-right-offset", "10"],
        ["--qr-bottom-offset", "10"],
    ],
)
def test_qr_options_are_rejected_outside_test_mode(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(arguments)


def test_qr_cli_rejects_bad_level_geometry_and_other_modes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--test-qr", "--qr-error-correction", "Z"])
    assert "invalid choice" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["--test-qr", "--qr-module-size", "0"])
    assert "positive integer" in capsys.readouterr().err
    for version in ("0", "-1", "41", "1.5", "invalid", ""):
        with pytest.raises(SystemExit):
            cli.main(["--test-qr", "--qr-version", version])
        assert "QR version must be 'auto' or an integer from 1 through 40" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["--test-qr", "--once"])


@pytest.mark.parametrize("version", [None, 4])
def test_qr_diagnostic_uses_no_content_or_production_persistence_and_publishes_exact_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, version: int | None
) -> None:
    caplog.set_level("INFO")
    config = create_config(tmp_path / "config", multiple_backends=True)
    (config.parent / "content").rmdir()
    monkeypatch.chdir(tmp_path)
    backends = {"window": RecordingBackend(), "image-server": RecordingBackend()}

    def unexpected_use(*_args, **_kwargs):
        pytest.fail("QR calibration must not access daily content or persistent state")

    monkeypatch.setattr(application, "load_content_library", unexpected_use)
    monkeypatch.setattr(application, "PersistentStateStore", unexpected_use)
    monkeypatch.setattr(application, "PreparedImageArtifactStore", unexpected_use)
    monkeypatch.setattr(application, "GlobalHistoryStore", unexpected_use)
    output, geometry = application.run_test_qr(
        config,
        QRCalibrationParameters(version=version, module_size=5, quiet_zone=2, right_offset=13, bottom_offset=7),
        backend_factory=lambda configuration: backends[configuration.type],
    )

    assert output == tmp_path / "refrain-qr-test.png"
    assert output.is_file()
    assert geometry.bounds[2] == geometry.image_size[0] - 13 - 1
    assert geometry.bounds[3] == geometry.image_size[1] - 7 - 1
    assert f"QR requested version: {version if version is not None else 'auto'}" in caplog.text
    assert f"QR resolved version: {version if version is not None else geometry.version}" in caplog.text
    assert "QR footprint pixel bounds (inclusive)" in caplog.text
    for backend in backends.values():
        assert backend.closed
        assert len(backend.images) == 1
    with Image.open(output) as saved:
        for backend in backends.values():
            assert saved.mode == backend.images[0].mode
            assert saved.size == backend.images[0].size
            assert saved.tobytes() == backend.images[0].tobytes()
    for backend in backends.values():
        for image in backend.images:
            image.close()


def test_qr_png_replacement_and_failed_save_preserve_previous_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = create_config(tmp_path / "config")
    monkeypatch.chdir(tmp_path)
    backend = RecordingBackend()
    output = tmp_path / "refrain-qr-test.png"
    application.run_test_qr(config, backend_factory=lambda _: backend)
    previous = output.read_bytes()

    original_save = Image.Image.save

    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(ApplicationError, match="cannot save QR diagnostic PNG.*disk full"):
        application.run_test_qr(
            config, QRCalibrationParameters(payload="replacement"), backend_factory=lambda _: backend
        )
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".refrain-qr-test-*.tmp"))
    monkeypatch.setattr(Image.Image, "save", original_save)

    application.run_test_qr(config, QRCalibrationParameters(payload="replacement"), backend_factory=lambda _: backend)
    assert output.read_bytes() != previous
    assert not list(tmp_path.glob(".refrain-qr-test-*.tmp"))
    for image in backend.images:
        image.close()


def test_fixed_version_capacity_failure_preserves_existing_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = create_config(tmp_path / "config")
    monkeypatch.chdir(tmp_path)
    backend = RecordingBackend()
    output = tmp_path / "refrain-qr-test.png"
    application.run_test_qr(config, backend_factory=lambda _: backend)
    previous = output.read_bytes()

    with pytest.raises(ApplicationError, match=r"version 1.*error-correction level M.*increase the version"):
        application.run_test_qr(
            config,
            QRCalibrationParameters(payload="x" * 100, version=1),
            backend_factory=lambda _: backend,
        )

    assert output.read_bytes() == previous
    assert len(backend.images) == 1
    assert backend.closed
    backend.images[0].close()


def test_qr_backend_failure_is_reported_and_png_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = create_config(tmp_path / "config")
    monkeypatch.chdir(tmp_path)

    class FailedBackend:
        def update(self, _image: Image.Image) -> None:
            raise RuntimeError("display failed")

        def close(self) -> None:
            self.closed = True

    backend = FailedBackend()
    with pytest.raises(ApplicationError, match="not published by every configured display backend"):
        application.run_test_qr(config, backend_factory=lambda _: backend)
    assert backend.closed
    assert (tmp_path / "refrain-qr-test.png").is_file()

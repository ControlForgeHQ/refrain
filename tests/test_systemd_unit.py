from configparser import ConfigParser
from importlib.resources import files


def test_systemd_template_uses_explicit_owner_and_bounded_supervision() -> None:
    unit = ConfigParser(interpolation=None)
    unit.read_string(files("refrain").joinpath("systemd", "refrain.service").read_text(encoding="utf-8"))

    assert unit["Unit"]["After"] == "time-set.target"
    assert "network-online.target" not in str(dict(unit["Unit"]))
    assert unit["Unit"]["StartLimitIntervalSec"] == "300"
    assert unit["Unit"]["StartLimitBurst"] == "5"
    assert unit["Service"]["User"] == "REPLACE_WITH_OWNER"
    assert unit["Service"]["Environment"] == '"HOME=/REPLACE/WITH/OWNER/HOME"'
    assert unit["Service"]["ExecStart"] == "/REPLACE/WITH/VENV/bin/refrain"
    assert unit["Service"]["Restart"] == "on-failure"
    assert unit["Service"]["RestartSec"] == "10"
    assert int(unit["Service"]["TimeoutStopSec"]) > 60
    assert unit["Service"]["StandardOutput"] == unit["Service"]["StandardError"] == "journal"
    assert unit["Install"]["WantedBy"] == "multi-user.target"


def test_image_server_template_is_independent_and_uses_required_supervision() -> None:
    root = files("refrain").joinpath("systemd")
    image_server = ConfigParser(interpolation=None)
    image_server.read_string(root.joinpath("refrain-image-server.service").read_text(encoding="utf-8"))
    resident = ConfigParser(interpolation=None)
    resident.read_string(root.joinpath("refrain.service").read_text(encoding="utf-8"))

    assert image_server["Unit"]["StartLimitIntervalSec"] == "300"
    assert image_server["Unit"]["StartLimitBurst"] == "5"
    assert image_server["Service"]["Type"] == "simple"
    assert image_server["Service"]["User"] == "REPLACE_WITH_OWNER"
    assert image_server["Service"]["Environment"] == '"HOME=/REPLACE/WITH/OWNER/HOME"'
    assert image_server["Service"]["ExecStart"] == "/REPLACE/WITH/VENV/bin/refrain-image-server"
    assert image_server["Service"]["Restart"] == "on-failure"
    assert image_server["Service"]["RestartSec"] == "10s"
    assert image_server["Service"]["RestartPreventExitStatus"] == "78"
    assert image_server["Service"]["TimeoutStopSec"] == "10s"
    assert image_server["Service"]["StandardOutput"] == image_server["Service"]["StandardError"] == "journal"
    assert image_server["Install"]["WantedBy"] == "multi-user.target"
    for unit, other in ((image_server, "refrain.service"), (resident, "refrain-image-server.service")):
        assert all(other not in value for section in unit.values() for value in section.values())
    assert set(image_server["Unit"]) == {"description", "startlimitintervalsec", "startlimitburst"}

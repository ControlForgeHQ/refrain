from configparser import ConfigParser
from importlib.resources import files


def test_systemd_template_uses_explicit_owner_and_bounded_supervision() -> None:
    unit = ConfigParser(interpolation=None)
    unit.read_string(files("refrain").joinpath("systemd", "refrain.service").read_text(encoding="utf-8"))

    assert unit["Unit"]["After"] == "time-set.target"
    assert "network-online.target" not in unit["Unit"]
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

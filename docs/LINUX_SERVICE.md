# Linux installation and systemd operation

This guide uses a system-level service owned by an existing, unprivileged user.
The initial hardware target is Raspberry Pi OS Lite 64-bit (Trixie) on a
Raspberry Pi 3B+ with the Waveshare 13.3-inch e-Paper HAT+ (E). It does not
require a desktop or a source checkout. Runtime and recovery behavior are
specified in [Architecture](ARCHITECTURE.md); configuration is specified in
[Content Format](CONTENT_FORMAT.md), and commands in [CLI](CLI.md).

## Install

Log in as the account that will own the installation, not root. Install the OS
Python 3.13 or newer, its venv support, and build tools (the hardware extra
may need to compile Python extensions):

```sh
sudo apt update
sudo apt install python3 python3-venv python3-dev build-essential
python3 --version
```

Obtain a trusted Refrain wheel distribution artifact and its dependencies for
the target system. Use a specific artifact and retain it and the resolved
dependency versions for repeatable deployment. The following commands use an
absolute wheel path and a user-owned venv outside the configuration and data
directories. Replace the path with the actual wheel:

```sh
WHEEL=/absolute/path/to/refrain-0.1.0-py3-none-any.whl
python3 -m venv "$HOME/refrain-venv"
"$HOME/refrain-venv/bin/python" -m pip install "$WHEEL[hardware]"
"$HOME/refrain-venv/bin/refrain" --initialize
```

Omit `[hardware]` for installations not using the Waveshare backend. For
offline installation, provide a wheelhouse with compatible wheels for Refrain
and its dependencies and add `--no-index --find-links /absolute/path/to/wheelhouse`
to the pip command. Do not install into system Python. The venv also provides
`refrain-viewer`. The package does not need the wheel or checkout at runtime.

Initialization creates the standard per-user configuration and content under
`${XDG_CONFIG_HOME:-$HOME/.config}/refrain`, state under
`${XDG_STATE_HOME:-$HOME/.local/state}/refrain`, and generated artifacts under
`${XDG_CACHE_HOME:-$HOME/.cache}/refrain`. It preserves existing user data.
Configure the installed `config.yaml` and content as described in
[Content Format](CONTENT_FORMAT.md). The default is an image server, not the
panel: configure `waveshare-13in3-e` for headless panel operation. Paths
explicitly configured in YAML may reside elsewhere and must remain accessible
to the owner.

For panel wiring, SPI overlay, device nodes, and group permissions, consult the
packaged hardware guide, for example:

```sh
"$HOME/refrain-venv/bin/python" -c 'from importlib.resources import files; print(files("refrain").joinpath("display/vendor/waveshare/README.md").read_text())'
```

In particular, enable the documented SPI overlay, reboot, inspect
`/dev/spidev0.0` and `/dev/gpiochip0`, and grant the owner access via the
device-node groups (commonly `spi` and `gpio`). Re-login or restart the service
after group changes. Do not run Refrain as root.

## Install the service

The wheel includes a template. Install it and edit the installed copy:

```sh
UNIT=$("$HOME/refrain-venv/bin/python" -c 'from importlib.resources import files; print(files("refrain").joinpath("systemd/refrain.service"))')
sudo install -m 0644 "$UNIT" /etc/systemd/system/refrain.service
sudoedit /etc/systemd/system/refrain.service
```

Replace `REPLACE_WITH_OWNER` with the existing non-root login name, the `HOME`
value with its absolute home directory, and `ExecStart` with the absolute path
to that venv's `bin/refrain`. Use systemd unit quoting/escaping if paths contain
spaces or special characters. The template is intentionally unusable until
these values are set. If the owner uses non-default `XDG_CONFIG_HOME`,
`XDG_STATE_HOME`, or `XDG_CACHE_HOME`, add corresponding absolute
`Environment="XDG_...=..."` lines matching the owner's interactive environment.
Likewise, make any other environment needed by the configuration consistent.
Use the same environment for initialization, control commands and maintenance;
otherwise they may address a different installation and ownership lock.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now refrain.service
systemctl status refrain.service
journalctl -u refrain.service -b
```

`sudo systemctl stop refrain.service`, `start`, and `restart` operate the
service. `sudo systemctl disable --now refrain.service` stops it and disables
boot startup without uninstalling it; `sudo systemctl enable --now
refrain.service` restores both. `journalctl -u refrain.service -f` follows
diagnostics. An intentional stop is not restarted. Unexpected failures are
restarted with a delay and a finite start-rate limit; after the limit is hit,
inspect the journal, correct the cause, then use `sudo systemctl reset-failed
refrain.service` and start it again.

The service orders after `time-set.target` when that target is present, but
does not wait for network or clock synchronization. Configure the OS timezone
and a reliable clock/time synchronization mechanism. A Pi without a reliable
RTC may start with an incorrect date: selection and reveal scheduling use the
local clock available at startup, and a later clock correction follows the
normal date-boundary and recovery rules. If a trustworthy time before the
first selection is essential, arrange it in the local system configuration;
do not assume this unit waits for NTP. See [Architecture](ARCHITECTURE.md) for
clock adjustment and recovery semantics.

Network is not a global startup prerequisite. A locally configured panel can
operate while an image-server listener is unavailable; the destination retries
according to the normal backend contract. Bind only to the intended interface:
image-server exposes unauthenticated HTTP to clients able to reach it. Interface
and firewall policy remain the operator's responsibility.

## Maintenance and removal

Stop the service before changing the venv. As the installation owner, install
the new trusted wheel into the same environment (include the hardware extra if
used), then start the service only after installation succeeds:

```sh
sudo systemctl stop refrain.service
WHEEL=/absolute/path/to/new-refrain-wheel.whl
"$HOME/refrain-venv/bin/python" -m pip install --upgrade "$WHEEL[hardware]"
sudo systemctl start refrain.service
systemctl status refrain.service
journalctl -u refrain.service -b
```

Back up configuration, content, custom assets and state before maintenance.
The venv update does not intentionally modify them. If troubleshooting
interactively, stop the service first and run `"$HOME/refrain-venv/bin/refrain"`
as the same owner with the same environment; stop it before restarting the
service. A normal or demo runtime cannot share ownership with the service;
one-shot controls such as `refrain --refresh` can be run by the owner while
the service is running.

To remove only service integration:

```sh
sudo systemctl disable --now refrain.service
sudo rm /etc/systemd/system/refrain.service
sudo systemctl daemon-reload
```

This does not delete the venv or user configuration, content, assets, state,
history, or artifacts. Remove the venv separately only if desired. Do not use
reset or purge as part of service removal.

## Manual Linux validation

This procedure requires a systemd-based Linux host; panel checks additionally
require the supported Raspberry Pi and Waveshare hardware. Record OS, Python,
hardware, configuration, results, and any limitations. Automated or mocked
tests do not establish physical display or boot behavior.

1. Install the wheel, initialize, configure the local panel, and verify device
   permissions as above. Install and enable the unit.
2. Check `systemctl status refrain.service` and `journalctl -u refrain.service
   -b`; visually confirm the presentation. Stop and start the service and check
   that shutdown and startup complete without errors.
3. While running, as the owner try `refrain` and `refrain --demo 10`: both must
   reject concurrent ownership. Verify `refrain-viewer --list-destinations`
   and `refrain --refresh` operate against the resident service. Invoke these
   commands from the venv and use the same environment as the service.
4. Record the current presentation and reveal progress. Restart the service
   and verify the current stage is restored; where practical test a missed
   reveal boundary and a changed logical display date.
5. Test abnormal termination with `sudo systemctl kill --kill-whom=main
   --signal=SIGKILL refrain.service`. Confirm the journal and status show an
   automatic restart and ownership is reacquired without deleting lock files.
   Then stop the service intentionally and confirm it stays stopped.
6. Enable and start the service, reboot, and verify it starts and presents
   without logging in. Check the clock and the current boot's journal.
7. With a local destination and an image-server bound to a removable network
   address, make that address unavailable before startup, then restore it.
   Confirm the local display works independently and the configured listener
   recovers without restarting Refrain. Repeat with the address removed and
   restored while running, where the network setup permits.
8. Stop the service, update the wheel as above, and restart. Confirm configuration,
   content, assets, state, and presentation recovery remain intact.

Physical panel operation, unattended reboot, and host-network changes require
maintainer validation on the actual deployment environment.

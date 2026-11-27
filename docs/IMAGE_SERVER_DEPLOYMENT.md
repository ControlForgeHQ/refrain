# Image-server deployment

This guide covers the independent `refrain-image-server` consumer on Raspberry Pi OS Lite 64-bit. The minimum supported Raspberry Pi is the 3B+; Refrain requires Python 3.13 or newer. Use a virtual environment with a compatible interpreter, including when the OS-provided Python is older. See [supported platforms](specifications/10-SYSTEM_CONTRACTS.md#supported-platform-and-portability) and [installation requirements](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#installation-requirements).

The [Image Server specification](specifications/75-IMAGE_SERVER.md) defines the service and HTTP behavior; [service operation](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#image-server-supervision), the [CLI](CLI.md#independent-image-server), and the [configuration schema](schemas/CONFIGURATION.md#independent-image-server-settings) are authoritative for supervision, invocation, and settings.

## Install and configure

Install the Refrain distribution and its declared dependencies in a virtual environment, for example:

```sh
python3.13 -m venv /opt/refrain/venv
/opt/refrain/venv/bin/python -m pip install /path/to/controlforge_refrain-VERSION-py3-none-any.whl
```

Replace the example paths and wheel filename with those of the installation; ensure the installation account can create the virtual environment at the selected location. The installed executables include `/opt/refrain/venv/bin/refrain-image-server`; no hardware extra is needed by the image server. The installed package resource `refrain/systemd/refrain-image-server.service` is a template, not an automatically installed or enabled system service. A source checkout is not needed to retrieve it.

Configure the resident to publish at least one destination and add an image-server section to the selected application configuration. For example, add the following destination to the existing `destinations` sequence and the separate top-level section:

```yaml
destinations:
  - id: "web-a"
    type: "publish"
    audience: "internal"
    aspect_ratio: "16:10"
    resolution: [1920, 1200]

image-server:
  destinations: ["web-a"]
  host: "127.0.0.1"
  port: 8080
```

This is a fragment, not a complete resident configuration. Retain the other required resident settings and destinations. Select only existing `publish` IDs; no destination is implicitly exposed. Configuration is loaded at startup, so restart the image server after changes. Merely adding this section does not enable or start the service. Missing publications do not prevent startup; requests return unavailable until a valid dataset exists.

The default bind address is loopback. For retrieval from another machine, set `host` to an appropriate address on a **trusted local network**, and limit network access with the host/network firewall. HTTP provides neither authentication nor encryption; never expose it directly to the public Internet or an untrusted network. Audience labels are not access controls. See [HTTP resource routing](specifications/75-IMAGE_SERVER.md#resource-routing).

### Identity and paths

Choose a non-root service account with permission to execute the virtual environment and read the selected configuration and configured publication datasets, including search permission on every parent directory. It does not need write access to publication datasets or authoritative state, hardware devices, or the resident's control credentials. A separate account and appropriately restricted group/ACL permissions can provide read-only access; ensure newly published files and directories remain readable by that account. Do not make private data world-readable to solve access problems.

The service's `HOME`, `XDG_CONFIG_HOME`, and `XDG_STATE_HOME` affect standard paths. Without overrides, Linux uses `~/.config/refrain/config.yaml` and `~/.local/state/refrain/publish`. An explicit `--config` selects that file, but does **not** relocate an omitted `storage.publish`: that default still uses the image-server account's XDG state location. A relative `storage.publish` is resolved against the selected configuration's directory; an absolute path is used as supplied. Ensure the resident and image server resolve the same publication root and that each selected destination is a direct child of it. See [effective runtime paths](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#effective-runtime-paths) and [storage](schemas/CONFIGURATION.md#storage).

## Install the unit

Extract the installed resource, then install a local copy for customization:

```sh
unit_dir=$(mktemp -d)
/opt/refrain/venv/bin/python -c 'from importlib.resources import files; print(files("refrain").joinpath("systemd", "refrain-image-server.service").read_text(encoding="utf-8"), end="")' > "$unit_dir/refrain-image-server.service"
sudo install -m 0644 "$unit_dir/refrain-image-server.service" /etc/systemd/system/refrain-image-server.service
rm "$unit_dir/refrain-image-server.service"
rmdir "$unit_dir"
sudoedit /etc/systemd/system/refrain-image-server.service
```

Replace `REPLACE_WITH_OWNER`, the `HOME` placeholder, and the executable path with the service account, its actual home, and the installed virtual environment's absolute executable path. If selecting a nonstandard configuration, append `--config /absolute/path/config.yaml` to `ExecStart`. Set any required absolute XDG environment values in the unit as well. Use systemd-compatible quoting for paths containing spaces. Ensure the account can traverse and read the chosen files. Do not leave placeholders in the deployed unit.

Keep the supplied supervision settings: configuration exit 78 is not restarted; other unsuccessful exits are eligible for restart after 10 seconds, limited to five starts per 300 seconds. The 10-second supervisor stop timeout accommodates the image server's five-second graceful shutdown allowance. Do not add dependencies on the resident unit. Reload systemd after installing or editing the unit:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now refrain-image-server.service
```

If binding to a specific LAN address, the address must exist before the listener starts. Otherwise repeated bind failures can exhaust the start limit before networking is ready. Where appropriate, configure the OS network manager's wait-online service and add `Wants=network-online.target` and `After=network-online.target` to a local image-server unit drop-in; verify that the network manager's definition of online actually covers the selected address. This is optional network ordering, not a dependency on the resident. After changing a drop-in, reload systemd and restart the image server; after a start-limit failure, inspect the journal and reset the failed state before starting it again.

Enablement is optional and independent of `refrain.service`. To run in the foreground instead, use the same identity and environment as the service and invoke `/opt/refrain/venv/bin/refrain-image-server --config /absolute/path/config.yaml`; omit `--config` only when the intended standard configuration is in that identity's environment. Stop the foreground instance before starting another instance on the same address and port.

## Operation and maintenance

Manage the consumer independently of the resident:

```sh
sudo systemctl start refrain-image-server.service
sudo systemctl stop refrain-image-server.service
sudo systemctl restart refrain-image-server.service
sudo systemctl disable refrain-image-server.service
systemctl status refrain-image-server.service
journalctl -u refrain-image-server.service -b --no-pager
```

`disable` prevents future automatic starts but does not stop a running service; use `disable --now` to do both. Starting or stopping either service does not manage the other. The image server can serve a previously verified publication while the resident is stopped.

For startup failure, inspect the journal, `systemctl status`, and `systemctl show refrain-image-server.service -p Result -p ExecMainStatus -p NRestarts`. Exit 78 indicates a missing configuration or invalid required configuration; correct the file, selected path, and access permissions, then use `sudo systemctl reset-failed refrain-image-server.service` and `sudo systemctl start refrain-image-server.service`. Exit 1 indicates listener or unrecoverable service failure; check the bind address, port conflicts, and journal. A 503 response can instead mean a missing, inaccessible, or invalid current dataset; check the effective publication root, directory traversal/read permissions, and resident publication diagnostics. Do not modify or repair a dataset as the consumer.

Consumers do not acquire the resident ownership lock. Before purging publication data or replacing consumer installation files, stop every affected consumer explicitly; stop the resident too when required by the relevant maintenance command. Restart consumers only after maintenance is complete and paths and permissions are restored. Reset and purge have different scopes; consult [consumer maintenance exclusion](specifications/80-INSTALLATION_AND_SERVICE_OPERATION.md#consumer-maintenance-exclusion) and the [CLI](CLI.md#primary-refrain-application).

## Raspberry Pi deployment validation

The following is a maintainer procedure, not a claim that hardware validation has already passed. Use a supported Raspberry Pi OS installation, a trusted local network, the actual service identity, and a resident configured to publish `web-a`. Record the Pi model, OS and Python versions, installed Refrain version, configuration, publication sizes, commands, results, and resource measurements. Use a maintenance window: these steps deliberately stop and kill the consumer. Replace example paths, destination, address, and port with the deployed values.

1. **Independent lifecycle.** Enable and start both units separately. Record `systemctl is-enabled` and `systemctl is-active` for each. Stop, start, and restart `refrain-image-server.service`, checking that `refrain.service` remains active and its main PID is unchanged. With a completed dataset available, stop the resident, confirm the image server remains active and can still serve it, then start the resident again. Check each unit's status and journal; restore the intended enablement state.
2. **Configuration failure.** Temporarily override only the image-server command using a disposable systemd drop-in and an invalid, readable configuration. The following example assumes the executable path above; first ensure the named drop-in does not already exist. Preserve any existing local customizations.

   ```sh
   sudo systemctl stop refrain-image-server.service
   printf 'image-server: {}\n' | sudo tee /run/refrain-image-server-invalid.yaml >/dev/null
   sudo mkdir -p /etc/systemd/system/refrain-image-server.service.d
   sudo tee /etc/systemd/system/refrain-image-server.service.d/99-validation.conf >/dev/null <<'EOF'
   [Service]
   ExecStart=
   ExecStart=/opt/refrain/venv/bin/refrain-image-server --config /run/refrain-image-server-invalid.yaml
   EOF
   sudo systemctl daemon-reload
   sudo systemctl reset-failed refrain-image-server.service
   sudo systemctl start refrain-image-server.service
   systemctl show refrain-image-server.service -p ActiveState -p Result -p ExecMainStatus -p NRestarts
   sleep 30
   systemctl show refrain-image-server.service -p ActiveState -p Result -p ExecMainStatus -p NRestarts
   journalctl -u refrain-image-server.service -b --no-pager
   ```

   The start is expected to fail with status 78; confirm the service remains failed and `NRestarts` does not increase after waiting longer than the restart interval. Then remove only the temporary drop-in and configuration, reload systemd, reset the failed state, and start the service with its original configuration:

   ```sh
   sudo rm /etc/systemd/system/refrain-image-server.service.d/99-validation.conf /run/refrain-image-server-invalid.yaml
   sudo systemctl daemon-reload
   sudo systemctl reset-failed refrain-image-server.service
   sudo systemctl start refrain-image-server.service
   ```

3. **Unexpected termination.** With the consumer active, record `systemctl show refrain-image-server.service -p MainPID -p NRestarts` and the resident PID. Run `sudo systemctl kill --kill-whom=main --signal=SIGKILL refrain-image-server.service`, wait longer than 10 seconds, and inspect status, journal, and both PIDs again. Confirm the consumer is active with a new PID and an increased restart count while the resident remains unchanged. If the start-rate limit is reached, inspect the failure and reset it before retrying; do not repeatedly kill a production service.
4. **Trusted-network retrieval.** From a second machine on the trusted LAN, run `curl --fail --show-error --dump-header /tmp/refrain-headers.txt --output /tmp/refrain-current.png http://PI_ADDRESS:8080/destination/web-a/current`. Confirm HTTP 200, `Content-Type: image/png`, a nonempty PNG, and successful image decoding. Compare its SHA-256 with the current manifest's `image_sha256` on the Pi, repeating if the resident published a new generation during the comparison. Also verify the service remains available while the resident is stopped. Avoid exposing image or metadata contents in shared logs.
5. **Performance and memory alongside the resident.** With the resident running and representative current publications, record both processes' baseline RSS and peak RSS (`ps -o pid,rss,cmd -p PID` and `/proc/PID/status` fields `VmRSS` and `VmHWM`). From the trusted client, perform repeated GETs, recording HTTP status, encoded byte count, and elapsed time (for example `curl --fail --silent --output /dev/null --write-out '%{http_code} %{size_download} %{time_total}\n' URL`). Sample both processes during and after requests and publication activity; record peak memory and observed retrieval/verification latency, dataset size, load, and any failures. Account for network transfer in client timings. Review the measurements for the target installation rather than treating hardware-independent tests as performance evidence.

Finally restore the normal configuration, service and enablement states, and any firewall settings used for the test. Report unperformed steps and observed limitations separately from automated Linux or Windows results. Physical embedded-client validation is outside this procedure.

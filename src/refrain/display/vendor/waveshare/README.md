# Waveshare 13.3-inch e-Paper HAT+ (E)

This is the authoritative installation, compatibility, provenance, licensing, and maintenance guide for Refrain's directly connected Waveshare display backend.

## Validated hardware

The validated combination is:

- Raspberry Pi 3 Model B+;
- Raspberry Pi OS Lite 64-bit (Trixie);
- Waveshare 13.3-inch e-Paper HAT+ (E).

Other Raspberry Pi models may work but have not been tested with this Linux SPI/GPIO transport. In particular, GPIO chip numbering and device permissions can vary; the implementation currently requests lines from `/dev/gpiochip0`, as validated on the Pi 3B+.

## Install and configure

### Configure SPI and GPIO

Edit `/boot/firmware/config.txt`:

1. Disable the existing `dtparam=spi=off` setting by commenting it out or removing it.
2. Under the `[all]` section, add the SPI overlay and retain the two GPIO output-low settings:

   ```ini
   [all]
   dtoverlay=spi0-0cs,no_miso
   gpio=7=op,dl
   gpio=8=op,dl
   ```

The `spi0-0cs` overlay enables SPI0 without assigning the panel's independent chip-select lines to the kernel SPI controller. GPIO7 and GPIO8 remain application-controlled chip selects; `gpio=...=op,dl` initializes each as an output driven low during boot. The backend requests both lines and sets them inactive (high) before controller communication. `dtoverlay=spi0-0cs,no_miso` enables the SPI controller and device interface, so a separate `dtparam=spi=on` is unnecessary.

Save the file and reboot:

```bash
sudo reboot
```

### Install Refrain and hardware dependencies

From the Refrain repository root, create a virtual environment and install the application with only the Waveshare hardware dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[hardware]'
```

For development, install the development and hardware extras together:

```bash
.venv/bin/python -m pip install -e '.[dev,hardware]'
```

These editable installs install Refrain and the selected optional dependencies. Ordinary installations and use of other display backends do not require `spidev` or `gpiod`.

The original Waveshare `DEV_Config_*.so` libraries are neither required nor installed.

### Verify devices and permissions

After reboot, verify that the expected interfaces exist:

```bash
ls -l /dev/spidev0.0 /dev/gpiochip0
```

The SPI interface is used in mode 0 at 1 MHz with kernel chip select disabled. The GPIO interface controls lines 7 (secondary chip select), 8 (master chip select), 17 (reset), 18 (power), 24 (BUSY), and 25 (DC held low).

Run Refrain as a non-root application user with read/write access to both device nodes. Inspect their owner and group with `ls -l`; on a standard Raspberry Pi OS setup, grant membership in the groups shown by the device nodes (commonly `spi` and `gpio`):

```bash
sudo usermod -aG spi,gpio <application-user>
```

Restart that user's session or the systemd service so the new group membership takes effect. If the device nodes use different groups, adjust the device permissions through the operating system's udev/group configuration rather than running Refrain as root.

## Physical presentation smoke test

Prepare a PNG with RGB color mode and dimensions of either 1200 × 1600 or 1600 × 1200. From the repository root, run the following, replacing `/path/to/compatible-rgb.png` with that file:

```bash
.venv/bin/python - /path/to/compatible-rgb.png <<'PY'
import sys
from PIL import Image
from refrain.display import create_display_backend

backend = create_display_backend("waveshare-13in3-e")
try:
    with Image.open(sys.argv[1]) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size not in {(1200, 1600), (1600, 1200)}:
            raise ValueError("expected an RGB PNG sized 1200 x 1600 or 1600 x 1200")
        backend.update(image)
finally:
    backend.close()
PY
```

`backend.close()` runs even if opening, validating, or presenting the image fails. A successful command confirms that the backend completed its update and cleanup calls; visually inspect the panel to verify image regions and orientation. Mocked tests do not establish physical display operation.

## Troubleshooting

- **`/dev/spidev0.0` is missing:** Confirm `dtparam=spi=off` is disabled, the overlay is under `[all]`, the `no_miso` spelling is correct, and the Pi was rebooted after editing the config.
- **`/dev/gpiochip0` is missing or GPIO requests fail:** Check the GPIO character-device interface and device-node permissions. The `/dev/gpiochip0` assumption is validated on the Pi 3B+ only; other Pi models may number GPIO chips differently and have not been tested.
- **Permission denied:** Check the service user's current supplementary groups and the group/permissions reported by `ls -l /dev/spidev0.0 /dev/gpiochip0`. Restart the service/session after changing group membership.
- **A GPIO line is busy:** Stop other applications or services that may own the panel's GPIO lines, then retry.
- **The backend cannot import `spidev` or `gpiod`:** Install the `hardware` extra in the same virtual environment used to run Refrain.
- **The panel does not show the expected image:** Confirm the panel connection, RGB mode, supported dimensions, SPI overlay, and GPIO permissions. A successful process exit does not replace visual validation on the physical panel.

## Upstream provenance

The model-specific controller driver originates from Waveshare's official e-Paper repository.

- **Manufacturer:** Waveshare Electronics
- **Hardware:** 13.3-inch e-Paper HAT+ (E)
- **Repository:** https://github.com/waveshareteam/e-Paper
- **Upstream directory:** `E-paper_Separate_Program/13.3inch_e-Paper_E/RaspberryPi/python/lib`
- **Upstream branch:** `master`
- **Verified upstream commit:** `d28b3c4cfc78eef1c6cd6e6e3013654e449d2864`
- **Verification date:** October 27, 2026
- **Manufacturer's manual:** https://www.waveshare.com/wiki/13.3inch_e-Paper_HAT+_(E)_Manual
- **Manufacturer's downloadable archive:** https://files.waveshare.com/wiki/13.3inch%20e-Paper%20HAT%2B/13.3inch_e-Paper_E.zip

## Vendored Python Files

The model-specific driver originates from upstream:

- `__init__.py`
- `epd13in3E.py`

The upstream Python source was verified against the corresponding Git blobs in the upstream repository at the commit identified above. `epdconfig.py` is a Refrain-owned compatibility shim, not upstream source. Local driver changes are documented below.

The previous implementation used externally supplied `DEV_Config_*.so` libraries. They are no longer runtime dependencies; the transport uses the optional `spidev` and `gpiod` Python packages and standard Linux device interfaces. Refrain does not bundle native Waveshare libraries.

The previously tracked binaries are removed from Git and explicitly ignored. Their SHA-256 values are retained here to identify the removed baseline files:

| File | SHA-256 |
|---|---|
| `DEV_Config_32_b.so` | `7d2cc363ed30139b622fec3bf5551b7ea1e58153a13769904fc11c6a8ae0bc79` |
| `DEV_Config_32_w.so` | `75c9251f9a5d9fd809ab8e1d605447e566137221208b6090920c50786262bd73` |
| `DEV_Config_64_b.so` | `6081eb6dd9e91c133ee8f68a012cac8e83270e0a077ce8544fecf028e86244c9` |
| `DEV_Config_64_w.so` | `1e6cb34707e35a601d3d6f119e48629cfc7dcfab40ac550546754d7a548df86a` |

The general-purpose driver collection under `RaspberryPi_JetsonNano/python/lib/waveshare_epd` is a separate implementation and is not the source of these files.

## Local Modifications

`epd13in3E.py` uses a package-relative import for `epdconfig` so the model-specific driver can be loaded from Refrain's vendored package. Its BUSY polling has a monotonic 120-second timeout. Image rows are gathered in their original order per controller before transmission, allowing the Linux transport to use bounded hardware-SPI writes while keeping each controller selected across transfer boundaries. The controller commands, timing, image quantization, and refresh operations are unchanged.

`epdconfig.py` maps the upstream driver's expected GPIO, SPI, delay, and lifecycle functions to `refrain.display.waveshare_transport`. The Refrain transport lazily acquires `/dev/spidev0.0` and GPIO lines via libgpiod, disables kernel chip select, sends mode-0 8-bit SPI at 1 MHz in bounded chunks, and releases both interfaces after each update. It marks communication and cleanup failures as poisoned to prevent unsafe reuse.

Any subsequent modifications to the upstream files must be documented and kept distinguishable from Refrain's own display-backend implementation.

## Licensing

The Python source files contain permissive license notices granting rights to use, modify, and redistribute the software, subject to retaining the copyright and permission notices.

The compiled native libraries from the original implementation are neither used nor redistributed. Their independently applicable license was not verified; this historical note does not create an installation requirement.

The original source-file license notices must be preserved. Refrain's MIT license must not be assumed to supersede or establish the licensing terms of third-party components.

## Maintenance

This directory contains the model-specific upstream controller implementation and its Refrain-owned Linux transport adapter used by the Waveshare display backend.

Update the vendor files deliberately rather than automatically. Before replacing them, compare the proposed upstream revision with the recorded baseline and review changes affecting image conversion, hardware initialization, SPI/GPIO communication, display refresh, and controller sleep.

Keep Refrain-specific display behaviour outside the vendor directory wherever practical.
# Waveshare 13.3-inch e-Paper HAT+ (E) Driver

## Origin

These files originate from Waveshare's official e-Paper repository.

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

Only the model-specific Python driver source is vendored:

- `__init__.py`
- `epd13in3E.py`
- `epdconfig.py`

The vendored Python files were verified against the corresponding Git blobs in the upstream repository at the commit identified above. Local changes are documented below.

The four native `DEV_Config_*.so` libraries are externally supplied runtime dependencies obtained by the user from Waveshare's official distribution. Refrain does not redistribute them. The vendored `epdconfig.py` retains its existing search order: the directory containing the module, `/usr/local/lib`, then `/usr/lib`. It selects the architecture-specific `32` or `64` library and the `_b` or `_w` variant based on the Raspberry Pi 5 detection.

The previously tracked binaries are removed from Git and explicitly ignored. Their SHA-256 values are retained here to identify the removed baseline files:

| File | SHA-256 |
|---|---|
| `DEV_Config_32_b.so` | `7d2cc363ed30139b622fec3bf5551b7ea1e58153a13769904fc11c6a8ae0bc79` |
| `DEV_Config_32_w.so` | `75c9251f9a5d9fd809ab8e1d605447e566137221208b6090920c50786262bd73` |
| `DEV_Config_64_b.so` | `6081eb6dd9e91c133ee8f68a012cac8e83270e0a077ce8544fecf028e86244c9` |
| `DEV_Config_64_w.so` | `1e6cb34707e35a601d3d6f119e48629cfc7dcfab40ac550546754d7a548df86a` |

The general-purpose driver collection under `RaspberryPi_JetsonNano/python/lib/waveshare_epd` is a separate implementation and is not the source of these files.

## Local Modifications

`epd13in3E.py` uses a package-relative import for `epdconfig` so the model-specific driver can be loaded from Refrain's vendored package. Its BUSY polling has a monotonic 120-second timeout; controller commands, timing, image quantization, and refresh operations are unchanged.

`epdconfig.py` checks the native `DEV_ModuleInit()` result before GPIO access. It calls `bcm2835_close()` after the bcm2835 variant's GPIO cleanup, checks its success result, and refuses further access after uncertain cleanup. The wiringPi variant does not use `bcm2835_close()`; `DEV_ModuleExit()` is void for both variants.

Any subsequent modifications to the upstream files must be documented and kept distinguishable from Refrain's own display-backend implementation.

## Licensing

The Python source files contain permissive license notices granting rights to use, modify, and redistribute the software, subject to retaining the copyright and permission notices.

The native shared libraries are distributed in Waveshare's official repository and downloadable driver archive and must be obtained and installed separately by users.

An independently applicable redistribution license for the compiled `.so` files has not been verified.

The original source-file license notices must be preserved. Refrain's MIT license must not be assumed to supersede or establish the licensing terms of third-party components.

## Maintenance

This directory contains the upstream hardware implementation used by Refrain's model-specific Waveshare display backend.

Update the vendor files deliberately rather than automatically. Before replacing them, compare the proposed upstream revision with the recorded baseline and review changes affecting image conversion, hardware initialization, SPI/GPIO communication, display refresh, and controller sleep.

Keep Refrain-specific display behaviour outside the vendor directory wherever practical.
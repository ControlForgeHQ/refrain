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

## Included Files

The following files are retained from the model-specific Waveshare Python distribution:

- `__init__.py`
- `epd13in3E.py`
- `epdconfig.py`
- `DEV_Config_32_b.so`
- `DEV_Config_32_w.so`
- `DEV_Config_64_b.so`
- `DEV_Config_64_w.so`

All seven files were verified to match the corresponding Git blobs in the upstream repository at the commit identified above.

The general-purpose driver collection under `RaspberryPi_JetsonNano/python/lib/waveshare_epd` is a separate implementation and is not the source of these files.

## Local Modifications

None at the time of import.

Any subsequent modifications to the upstream files must be documented and kept distinguishable from Refrain's own display-backend implementation.

## Licensing

The Python source files contain permissive license notices granting rights to use, modify, and redistribute the software, subject to retaining the copyright and permission notices.

The native shared libraries are distributed alongside those source files in Waveshare's official repository and downloadable driver archive.

An independently applicable redistribution license for the compiled `.so` files has not been verified.

The original source-file license notices must be preserved. Refrain's MIT license must not be assumed to supersede or establish the licensing terms of third-party components.

## Maintenance

This directory contains the upstream hardware implementation used by Refrain's model-specific Waveshare display backend.

Update the vendor files deliberately rather than automatically. Before replacing them, compare the proposed upstream revision with the recorded baseline and review changes affecting image conversion, hardware initialization, SPI/GPIO communication, display refresh, and controller sleep.

Keep Refrain-specific display behaviour outside the vendor directory wherever practical.
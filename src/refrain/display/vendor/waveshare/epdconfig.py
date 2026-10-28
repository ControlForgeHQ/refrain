"""Compatibility names binding the vendored driver to Refrain's Linux transport."""

from refrain.display.waveshare_transport import (
    EPD_BUSY_PIN,
    EPD_CS_M_PIN,
    EPD_CS_S_PIN,
    EPD_DC_PIN,
    EPD_PWR_PIN,
    EPD_RST_PIN,
    delay_ms,
    digital_read,
    digital_write,
    is_initialized,
    is_poisoned,
    module_exit,
    module_init,
    spi_writebyte,
    spi_writebyte2,
)

__all__ = [
    "EPD_BUSY_PIN",
    "EPD_CS_M_PIN",
    "EPD_CS_S_PIN",
    "EPD_DC_PIN",
    "EPD_PWR_PIN",
    "EPD_RST_PIN",
    "delay_ms",
    "digital_read",
    "digital_write",
    "is_initialized",
    "is_poisoned",
    "module_exit",
    "module_init",
    "spi_writebyte",
    "spi_writebyte2",
]

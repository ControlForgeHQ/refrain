# /*****************************************************************************
# * | File        :	  epdconfig.py
# * | Author      :   Waveshare electrices
# * | Function    :   Hardware underlying interface
# * | Info        :
# *----------------
# * |	This version:   V1.0
# * | Date        :   2019-11-01
# * | Info        :   
# ******************************************************************************/
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
import time
import os
import logging
import sys

from ctypes import *
import ctypes

EPD_SCK_PIN     =11
EPD_MOSI_PIN    =10

EPD_CS_M_PIN    =8
EPD_CS_S_PIN    =7


EPD_DC_PIN      =25
EPD_RST_PIN     =17
EPD_BUSY_PIN    =24
EPD_PWR_PIN     =18
 
find_dirs = [
    os.path.dirname(os.path.realpath(__file__)),
    '/usr/local/lib',
    '/usr/lib',
]
spi = None
_library_variant = None
for find_dir in find_dirs:
    val = int(os.popen('getconf LONG_BIT').read())
    val_1 = os.popen("cat /proc/cpuinfo | grep 'Raspberry Pi 5'").read()
    if val == 64:
        if val_1 == "":
            so_filename = os.path.join(find_dir, 'DEV_Config_64_b.so')
        else:
            so_filename = os.path.join(find_dir, 'DEV_Config_64_w.so')
    else:
        if val_1 == "":
            so_filename = os.path.join(find_dir, 'DEV_Config_32_b.so')
        else:
            so_filename = os.path.join(find_dir, 'DEV_Config_32_w.so')
    if os.path.exists(so_filename):
        spi = CDLL(so_filename)
        _library_variant = os.path.basename(so_filename).split("_")[-1][0]
        break
if spi is None:
    raise RuntimeError(
        f"required Waveshare native library {os.path.basename(so_filename)} was not found; "
        "obtain the matching architecture/variant from Waveshare and install it beside epdconfig.py, "
        "in /usr/local/lib, or in /usr/lib"
    )

spi.DEV_ModuleInit.restype = ctypes.c_ubyte
spi.DEV_ModuleExit.restype = None
if _library_variant == "b":
    spi.bcm2835_close.restype = ctypes.c_ubyte

_native_state = "inactive"

def digital_write(pin, value):
    spi.DEV_Digital_Write(pin, value)

def digital_read(pin):
    return spi.DEV_Digital_Read(pin)

def spi_writebyte(value): 
    spi.DEV_SPI_SendData(value)

def spi_writebyte2(buf, len): 
    array_data = (ctypes.c_ubyte * len)(*buf)
    spi.DEV_SPI_SendData_nByte(array_data, ctypes.c_ulong(len))
 
def delay_ms(delaytime):
    time.sleep(delaytime / 1000.0)
        
def module_init():
    global _native_state
    if _native_state != "inactive":
        raise RuntimeError(f"native GPIO library is {_native_state}; refusing to initialize it again")
    try:
        result = spi.DEV_ModuleInit()
    except Exception:
        _native_state = "poisoned"
        raise
    if result != 0:
        _native_state = "poisoned"
        raise RuntimeError(f"native DEV_ModuleInit failed with status {result}")
    _native_state = "active"
    try:
        spi.DEV_Digital_Write(EPD_PWR_PIN, 1)
        time.sleep(30 / 1000.0)
        spi.DEV_Digital_Write(EPD_PWR_PIN, 0)
        time.sleep(30 / 1000.0)
        spi.DEV_Digital_Write(EPD_PWR_PIN, 1)
        time.sleep(30 / 1000.0)
    except Exception:
        try:
            module_exit()
        except Exception:
            logging.exception("failed to release native GPIO after module initialization failure")
        raise


def module_exit():
    global _native_state
    if _native_state == "inactive":
        return
    if _native_state != "active":
        raise RuntimeError(f"native GPIO library is {_native_state}; refusing to access it")
    try:
        spi.DEV_ModuleExit()
        if _library_variant == "b" and spi.bcm2835_close() != 1:
            raise RuntimeError("native bcm2835_close failed")
    except Exception:
        _native_state = "poisoned"
        raise
    _native_state = "inactive"


def is_initialized():
    return _native_state == "active"


def is_poisoned():
    return _native_state == "poisoned"

  
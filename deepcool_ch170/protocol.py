"""HID report for the CH170 / CH270 / CH690 second-generation panel.

The firmware shows fixed pages. Each page is four slots, and the slot
layout cannot be rearranged:

- cpu: temperature, watts, usage, clock (MHz)
- gpu: temperature, watts, usage, clock (MHz). The case prints MHz on this page.
- psu: temperature, watts, usage, fan. The case prints FAN only on this page.

Byte positions match Nortank12/deepcool-digital-linux ch_series_gen2.
"""

import struct

REPORT_SIZE = 64
PAGE_CODE = {"cpu": 2, "gpu": 4, "psu": 5}


def _u16(buf, offset, value):
    buf[offset : offset + 2] = struct.pack(">H", max(0, min(65535, int(value))))


def _temp(buf, offset, celsius):
    buf[offset : offset + 4] = struct.pack(">f", float(celsius))


def build_packet(page, fahrenheit, reading):
    if page not in PAGE_CODE:
        raise ValueError(page)
    buf = bytearray(REPORT_SIZE)
    buf[0] = 16
    buf[1] = 104
    buf[2] = 1
    buf[3] = 6
    buf[4] = 35
    buf[5] = 1
    buf[6] = PAGE_CODE[page]
    buf[9] = 1 if fahrenheit else 0

    cpu_temp = _display_temp(reading.cpu_temp_c, fahrenheit)
    gpu_temp = _display_temp(reading.gpu_temp_c, fahrenheit)

    if page == "cpu":
        _u16(buf, 7, reading.cpu_watts)
        _temp(buf, 10, cpu_temp)
        buf[14] = _pct(reading.cpu_pct)
        _u16(buf, 15, reading.cpu_mhz)
    elif page == "gpu":
        _u16(buf, 19, reading.gpu_watts)
        _temp(buf, 21, gpu_temp)
        buf[25] = _pct(reading.gpu_pct)
        _u16(buf, 26, reading.gpu_mhz)
    else:
        _u16(buf, 28, reading.psu_watts)
        psu_temp = 0 if reading.psu_temp_c is None else _display_temp(reading.psu_temp_c, fahrenheit)
        _temp(buf, 30, psu_temp)
        buf[34] = _pct(reading.psu_pct)
        _u16(buf, 37, 0 if reading.psu_rpm is None else reading.psu_rpm)

    buf[40] = sum(buf[1:40]) % 256
    buf[41] = 22
    return bytes(buf)


def _display_temp(celsius, fahrenheit):
    value = float(celsius)
    if fahrenheit:
        value = value * 9.0 / 5.0 + 32.0
    return int(round(value))


def _pct(value):
    return max(0, min(100, int(value)))

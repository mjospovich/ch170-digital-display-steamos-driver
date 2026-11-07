# Device and sensors

## USB

| Field | Value |
|---|---|
| Vendor | DeepCool `3633` |
| Product | CH170 DIGITAL `0013` |
| Class | HID |
| Kernel driver | `usbhid` / `hid-generic` |

No out-of-tree kernel module is required. The driver speaks HID reports from userspace.

Product id `19` in the upstream device table is the decimal form of `0x0013`.

## Report

64 bytes. The panel consumes one report per update.

| Offset | Value |
|---|---|
| 0 | report id `16` |
| 1–5 | fixed header `104, 1, 6, 35, 1` |
| 6 | page: `2` CPU, `4` GPU, `5` PSU |
| 9 | `0` Celsius, `1` Fahrenheit |
| 7–8 | CPU power, uint16 big-endian watts |
| 10–13 | CPU temperature, float32 big-endian |
| 14 | CPU usage, 0–100 |
| 15–16 | CPU clock, uint16 big-endian MHz |
| 19–20 | GPU power, uint16 big-endian watts |
| 21–24 | GPU temperature, float32 big-endian |
| 25 | GPU usage, 0–100 |
| 26–27 | GPU clock, uint16 big-endian MHz |
| 28–29 | PSU power, uint16 big-endian watts |
| 30–33 | PSU temperature, float32 big-endian |
| 34 | PSU usage, 0–100 |
| 37–38 | PSU fan, uint16 big-endian rpm |
| 40 | checksum, `sum(bytes 1..39) mod 256` |
| 41 | terminator `22` |

## Sensors

| Reading | Source |
|---|---|
| CPU temperature | hwmon `k10temp` `temp1_input` |
| CPU power | RAPL package energy, `intel-rapl:0/energy_uj`, differenced over the update interval |
| CPU usage | aggregate `/proc/stat` |
| CPU clock | highest `cpu MHz` in `/proc/cpuinfo` |
| GPU temperature | `amdgpu` `temp1_input` on the selected PCI device |
| GPU power | `amdgpu` `power1_average` |
| GPU usage | `gpu_busy_percent` |
| GPU clock | `gpu_metrics` current GFX clock, else the starred `pp_dpm_sclk` value. 0 while the engine is in GFXOFF |
| PSU | hwmon device whose name contains `psu`, when present. Otherwise the estimate in [ch170-display.md](ch170-display.md) |

`gpu_pci` of `auto` selects the AMD GPU that has a connected display output.

The udev rule marks the CH170 hidraw node writable and the RAPL energy files world-readable, because the kernel creates those energy files as mode `0400`.

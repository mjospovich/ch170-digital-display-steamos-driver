# Operation

`deepcool-digital.service` runs `python3 -m deepcool_ch170`. It writes one 64-byte HID report about once a second. Settings live in `config/display.json`. The process reloads that file on every update.

`bin/ch170-display` opens the settings window. `bin/install-system.sh` installs the service, the udev rule, and the menu entry. `bin/uninstall-system.sh` removes those and leaves this directory in place.

## Pages

The four slots on a page are fixed by the panel firmware.

| Page | Slots |
|---|---|
| CPU | temperature, package power, whole-CPU usage, fastest-core clock |
| GPU | edge temperature, board power, 3D engine busy, graphics clock |
| PSU | temperature, power, usage, fan |

CPU and GPU pages label the last slot MHz. The PSU page labels it FAN.

CPU usage is aggregate: 100% means every thread was busy for that interval. CPU clock is the highest core clock in `/proc/cpuinfo` at that moment.

GPU clock is the current graphics clock. 0 MHz means the graphics engine is powered down (AMD GFXOFF). Under load the same slot is the live clock. The driver does not replace 0 with another value.

## PSU estimate

Without a PSU sensor the power slot is:

`CPU package power + GPU board power + psu_overhead_w`

`psu_overhead_w` defaults to 30. It covers parts the driver cannot read: memory modules, storage, fans, lighting, and the chipset. Set it to 0 to show only CPU plus GPU.

`psu_capacity_w` is the supply rating in watts. Usage on the PSU page is `power / psu_capacity_w`. A value of 0 leaves the usage slot empty.

Extra W and Supply W appear in the window only when the PSU page is selected.

A hwmon device whose name contains `psu` overrides the estimate:

| Sensor present | Effect |
|---|---|
| `temp1_input` | PSU temperature slot |
| `fan1_input` | PSU fan slot, in rpm |
| `power1_input` | replaces the estimate; not added to it |

Temperature and fan stay empty when those files are absent.

## Configuration

| Key | Meaning |
|---|---|
| `mode` | `auto`, `cpu`, `gpu`, or `psu` |
| `pages` | pages included when `mode` is `auto` |
| `dwell_sec` | seconds on each page in `auto` |
| `update_ms` | report interval |
| `fahrenheit` | `true` sends °F |
| `gpu_pci` | PCI address, or `auto` for the GPU with a connected output |
| `enabled` | `false` stops reports and clears the panel to zeros. The service stays installed |
| `psu_overhead_w` | watts added to CPU + GPU. Default 30 |
| `psu_capacity_w` | supply rating. `0` leaves usage empty |

One process should own the HID device. A second writer interleaves reports.

Restart after a code change:

```bash
sudo systemctl restart deepcool-digital.service
```

Preview from the repository root:

```bash
PYTHONPATH=. python3 -m deepcool_ch170 --preview
```

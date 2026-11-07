"""Live CPU, GPU, and estimated PSU numbers for the CH170 packet."""

import struct
import time
from dataclasses import dataclass
from pathlib import Path

ENERGY_UJ = Path("/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj")
ENERGY_MAX = Path("/sys/class/powercap/intel-rapl/intel-rapl:0/max_energy_range_uj")
CORE_ENERGY_UJ = Path("/sys/class/powercap/intel-rapl/intel-rapl:0/intel-rapl:0:0/energy_uj")

# gpu_metrics format 1, content 1..3. current_gfxclk then current_uclk.
# Checked against the RX 9070 table: current_uclk matches pp_dpm_mclk.
_GFX_MHZ = 54
_UCLK_MHZ = 58


@dataclass
class Reading:
    cpu_temp_c: float = 0.0
    cpu_watts: int = 0
    cpu_pct: int = 0
    cpu_mhz: int = 0
    gpu_temp_c: float = 0.0
    gpu_watts: int = 0
    gpu_pct: int = 0
    gpu_mhz: int = 0
    psu_watts: int = 0
    psu_pct: int = 0
    psu_temp_c: float | None = None
    psu_rpm: int | None = None
    cpu_core_watts: int | None = None
    cpu_soc_watts: int | None = None


class Sampler:
    """CPU watts and usage need two samples. The first read only stores a baseline."""

    def __init__(self):
        self._energy = None
        self._core = None
        self._stat = None
        self._when = None
        self._max_uj = _read_int(ENERGY_MAX)

    def read(self, cfg):
        now = time.monotonic()
        energy = _read_int(ENERGY_UJ)
        core_energy = _read_int(CORE_ENERGY_UJ)
        stat = _cpu_stat()
        if self._when is None:
            watts = 0
            pct = 0
            core_watts = None
        else:
            dt = max(0.001, now - self._when)
            watts = watts_from_uj(self._energy, energy, dt, self._max_uj)
            pct = busy_percent(self._stat, stat)
            core_watts = watts_from_uj(self._core, core_energy, dt, self._max_uj)
            if self._core is None or core_energy is None:
                core_watts = None
        self._energy = energy
        self._core = core_energy
        self._stat = stat
        self._when = now
        soc_watts = None if core_watts is None else max(0, watts - core_watts)

        pci = cfg.gpu_pci
        if pci == "auto":
            pci = find_display_gpu() or ""
        gpu_temp, gpu_watts, gpu_pct, gpu_mhz = sample_gpu(pci)
        cpu_temp = cpu_temp_c()
        cpu_mhz = fastest_core_mhz()
        measured_w, psu_temp, psu_rpm = sample_psu_hwmon()
        if measured_w is None:
            psu_watts = max(0, watts + gpu_watts + cfg.psu_overhead_w)
        else:
            psu_watts = measured_w
        psu_pct = 0
        if cfg.psu_capacity_w > 0:
            psu_pct = min(100, int(round(100 * psu_watts / cfg.psu_capacity_w)))
        return Reading(
            cpu_temp_c=cpu_temp,
            cpu_watts=watts,
            cpu_pct=pct,
            cpu_mhz=cpu_mhz,
            gpu_temp_c=gpu_temp,
            gpu_watts=gpu_watts,
            gpu_pct=gpu_pct,
            gpu_mhz=gpu_mhz,
            psu_watts=psu_watts,
            psu_pct=psu_pct,
            psu_temp_c=psu_temp,
            psu_rpm=psu_rpm,
            cpu_core_watts=core_watts,
            cpu_soc_watts=soc_watts,
        )


def busy_percent(prev, curr):
    """Whole-chip busy time from the aggregate /proc/stat line, 0-100.

    100 means every thread was busy for the whole interval. It is not the
    busiest core, and it is not an average that can exceed 100.
    """
    if not prev or not curr:
        return 0
    total0, idle0 = _total_idle(prev)
    total1, idle1 = _total_idle(curr)
    delta = total1 - total0
    if delta <= 0:
        return 0
    pct = (1.0 - (idle1 - idle0) / delta) * 100.0
    return int(max(0, min(100, round(pct))))


def watts_from_uj(prev, curr, dt_s, max_uj):
    if prev is None or curr is None or dt_s <= 0:
        return 0
    delta = curr - prev
    if delta < 0 and max_uj:
        delta += max_uj
    if delta < 0:
        return 0
    return int(round(delta / 1_000_000 / dt_s))


def choose_gfx_mhz(current, starred, levels, policy):
    """Prefer the live metrics clock. The 9070 reports 0 while the core is gated."""
    if _sane_mhz(current):
        return current
    if _sane_mhz(starred):
        return starred
    if policy == "lowest_step":
        positive = [mhz for mhz in levels if _sane_mhz(mhz)]
        if positive:
            return min(positive)
    return 0


def parse_dpm_sclk(text):
    starred = None
    levels = []
    for line in text.splitlines():
        mark = "*" in line
        body = line.replace("*", "").strip()
        if ":" not in body:
            continue
        _, rest = body.split(":", 1)
        digits = "".join(ch for ch in rest if ch.isdigit())
        if not digits:
            continue
        mhz = int(digits)
        levels.append(mhz)
        if mark:
            starred = mhz
    return starred, levels


def parse_gpu_metrics(data):
    if len(data) < _UCLK_MHZ + 2:
        return {"gfx_mhz": 0, "uclk_mhz": 0}
    size, fmt, content = struct.unpack_from("<HBB", data, 0)
    if fmt != 1 or content < 1 or size < _UCLK_MHZ + 2:
        return {"gfx_mhz": 0, "uclk_mhz": 0}
    gfx = struct.unpack_from("<H", data, _GFX_MHZ)[0]
    uclk = struct.unpack_from("<H", data, _UCLK_MHZ)[0]
    return {
        "gfx_mhz": gfx if _sane_mhz(gfx) else 0,
        "uclk_mhz": uclk if _sane_mhz(uclk) else 0,
    }


def sample_psu_hwmon():
    """Real supply telemetry, if a kernel driver published it.

    Watts replace the CPU+GPU estimate. Temperature and fan fill those
    slots on the PSU page. Returns (watts or None, temp C or None, rpm or None).
    """
    root = Path("/sys/class/hwmon")
    if not root.exists():
        return None, None, None
    hwmon = None
    for entry in root.glob("hwmon*"):
        name = (_read_text(entry / "name") or "").lower()
        if "psu" in name:
            hwmon = entry
            break
    if hwmon is None:
        return None, None, None
    temp = _milli(hwmon / "temp1_input") if (hwmon / "temp1_input").exists() else None
    rpm = _read_int(hwmon / "fan1_input") if (hwmon / "fan1_input").exists() else None
    watts = _hwmon_watts(hwmon / "power1_input")
    return watts, temp, rpm


def _hwmon_watts(path):
    raw = _read_int(path)
    if raw is None:
        return None
    # hwmon power is microwatts. A small integer is already watts.
    if raw > 5000:
        return max(0, int(round(raw / 1_000_000)))
    return max(0, raw)


def sample_gpu(pci):
    if not pci:
        return 0.0, 0, 0, 0
    base = Path("/sys/bus/pci/devices") / pci
    hwmon = _hwmon(base)
    temp = _milli(hwmon / "temp1_input") if hwmon else 0.0
    watts = int(round(_micro(hwmon / "power1_average") / 1_000_000)) if hwmon else 0
    pct = _read_int(base / "gpu_busy_percent") or 0
    metrics = parse_gpu_metrics(_read_bytes(base / "gpu_metrics"))
    starred, levels = parse_dpm_sclk(_read_text(base / "pp_dpm_sclk") or "")
    # 0 MHz is the core powered down (GFXOFF). Do not substitute another clock.
    mhz = choose_gfx_mhz(metrics["gfx_mhz"], starred, levels, "zero")
    return temp, max(0, watts), max(0, min(100, pct)), mhz


def find_display_gpu():
    root = Path("/sys/class/drm")
    if not root.exists():
        return None
    for status in root.glob("card*-*/status"):
        if _read_text(status) != "connected":
            continue
        card = status.parent.name.split("-", 1)[0]
        pci = _pci_of_card(card)
        if pci and _is_amd(pci):
            return pci
    fallback = None
    for device in Path("/sys/bus/pci/devices").glob("*"):
        if not _is_amd(device.name):
            continue
        dev_id = _read_text(device / "device")
        if dev_id and dev_id.lower().endswith("13c0"):
            fallback = fallback or device.name
            continue
        return device.name
    return fallback


def cpu_temp_c():
    root = Path("/sys/class/hwmon")
    if not root.exists():
        return 0.0
    for hwmon in root.glob("hwmon*"):
        if _read_text(hwmon / "name") == "k10temp":
            return _milli(hwmon / "temp1_input")
    return 0.0


def fastest_core_mhz():
    best = 0.0
    try:
        lines = Path("/proc/cpuinfo").read_text().splitlines()
    except OSError:
        return 0
    for line in lines:
        if line.startswith("cpu MHz"):
            try:
                best = max(best, float(line.split(":", 1)[1]))
            except ValueError:
                continue
    return int(round(best))


def _cpu_stat():
    try:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        return [int(field) for field in fields]
    except (OSError, ValueError, IndexError):
        return None


def _total_idle(fields):
    vals = list(fields[:8])
    if len(vals) < 5:
        return 0, 0
    idle = vals[3] + vals[4]
    return sum(vals), idle


def _sane_mhz(value):
    return isinstance(value, int) and 0 < value < 10000


def _hwmon(pci):
    entries = list((pci / "hwmon").glob("hwmon*")) if (pci / "hwmon").exists() else []
    return entries[0] if entries else None


def _pci_of_card(card):
    device = Path("/sys/class/drm") / card / "device"
    try:
        return device.resolve().name
    except OSError:
        return None


def _is_amd(pci):
    vendor = _read_text(Path("/sys/bus/pci/devices") / pci / "vendor")
    return vendor is not None and vendor.lower().endswith("1002")


def _read_text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _read_bytes(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def _read_int(path):
    text = _read_text(path)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _milli(path):
    value = _read_int(path)
    return 0.0 if value is None else value / 1000.0


def _micro(path):
    value = _read_int(path)
    return 0 if value is None else value

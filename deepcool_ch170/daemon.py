"""Push a CH170 report about once a second. Reloads config/display.json live."""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .config import ROOT, load
from .protocol import build_packet
from .sensors import Reading, Sampler

HID_VENDOR = "3633"
HID_PRODUCT = "0013"


def main():
    parser = argparse.ArgumentParser(description="CH170 DIGITAL panel")
    parser.add_argument("--preview", action="store_true", help="print one reading and exit")
    args = parser.parse_args()
    if args.preview:
        preview()
    else:
        run()


def preview():
    cfg = load()
    sampler = Sampler()
    sampler.read(cfg)
    time.sleep(cfg.update_ms / 1000)
    reading = sampler.read(cfg)
    pci = find_pci(cfg)
    print(f"gpu {pci}")
    print(
        f"cpu {reading.cpu_temp_c:.0f}C {reading.cpu_watts}W "
        f"{reading.cpu_pct}% {reading.cpu_mhz}MHz"
    )
    print(
        f"gpu {reading.gpu_temp_c:.0f}C {reading.gpu_watts}W "
        f"{reading.gpu_pct}% {reading.gpu_mhz}MHz"
    )
    print(f"psu {reading.psu_watts}W usage {reading.psu_pct}% (cpu+gpu+{cfg.psu_overhead_w}W)")


def find_pci(cfg):
    from .sensors import find_display_gpu

    if cfg.gpu_pci != "auto":
        return cfg.gpu_pci
    return find_display_gpu() or "none"


def run():
    device = HidPanel()
    sampler = Sampler()
    cycle = Cycle()
    cfg = load()
    sampler.read(cfg)
    print("CH170 panel daemon", flush=True)
    running = True
    while True:
        cfg = load()
        time.sleep(min(cfg.update_ms, 1000) / 1000 if not cfg.enabled else cfg.update_ms / 1000)
        if not cfg.enabled:
            if running:
                try:
                    device.write(build_packet("cpu", False, Reading()))
                except OSError:
                    device.close()
                print("display off", flush=True)
            running = False
            continue
        if not running:
            print("display on", flush=True)
        running = True
        reading = sampler.read(cfg)
        page = cycle.current(cfg, time.monotonic())
        packet = build_packet(page, cfg.fahrenheit, reading)
        _write_live(page, reading)
        try:
            device.write(packet)
        except OSError as exc:
            print(f"panel write failed: {exc}", file=sys.stderr, flush=True)
            device.close()
            time.sleep(1)
            continue
        if page != cycle.logged:
            cycle.logged = page
            print(_line(page, reading), flush=True)


def _write_live(page, reading):
    path = ROOT / "run" / "live.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(reading)
    payload["page"] = page
    payload["time"] = time.time()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


def _line(page, reading):
    return (
        f"page {page}  cpu {reading.cpu_temp_c:.0f}C {reading.cpu_watts}W "
        f"{reading.cpu_pct}% {reading.cpu_mhz}MHz  "
        f"gpu {reading.gpu_temp_c:.0f}C {reading.gpu_watts}W "
        f"{reading.gpu_pct}% {reading.gpu_mhz}MHz  "
        f"psu {reading.psu_watts}W"
    )


class Cycle:
    def __init__(self):
        self.page = None
        self.until = 0.0
        self.logged = None

    def current(self, cfg, now):
        pages = list(cfg.pages) if cfg.mode == "auto" else [cfg.mode]
        if self.page not in pages or now >= self.until:
            if self.page not in pages:
                self.page = pages[0]
            else:
                index = pages.index(self.page)
                self.page = pages[(index + 1) % len(pages)]
            self.until = now + cfg.dwell_sec
        return self.page


class HidPanel:
    def __init__(self):
        self._fd = None

    def write(self, packet):
        if self._fd is None:
            path = hidraw_path()
            if path is None:
                raise OSError("CH170 HID device not found")
            self._fd = os.open(path, os.O_RDWR)
        os.write(self._fd, packet)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def hidraw_path():
    root = Path("/sys/class/hidraw")
    if not root.exists():
        return None
    for node in root.glob("hidraw*"):
        uevent = node / "device" / "uevent"
        try:
            text = uevent.read_text()
        except OSError:
            continue
        if f"{HID_VENDOR.upper()}" in text.upper() and HID_PRODUCT in text.lower():
            # HID_ID=0003:00003633:00000013
            if "00003633" in text.lower() and "00000013" in text.lower():
                return Path("/dev") / node.name
    return None

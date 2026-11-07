import struct
import unittest

from deepcool_ch170.config import Config
from deepcool_ch170.protocol import build_packet
from deepcool_ch170.sensors import (
    Reading,
    busy_percent,
    choose_gfx_mhz,
    parse_dpm_sclk,
    parse_gpu_metrics,
    watts_from_uj,
)


def _reading():
    return Reading(
        cpu_temp_c=60,
        cpu_watts=80,
        cpu_pct=10,
        cpu_mhz=5200,
        gpu_temp_c=40,
        gpu_watts=11,
        gpu_pct=2,
        gpu_mhz=1800,
        psu_watts=91,
        psu_pct=18,
    )


class PacketTests(unittest.TestCase):
    def test_cpu_page_fields_and_checksum(self):
        pkt = build_packet("cpu", False, _reading())
        self.assertEqual(len(pkt), 64)
        self.assertEqual(pkt[0], 16)
        self.assertEqual(pkt[6], 2)
        self.assertEqual(pkt[9], 0)
        self.assertEqual(int.from_bytes(pkt[7:9], "big"), 80)
        self.assertEqual(struct.unpack(">f", pkt[10:14])[0], 60)
        self.assertEqual(pkt[14], 10)
        self.assertEqual(int.from_bytes(pkt[15:17], "big"), 5200)
        self.assertEqual(pkt[41], 22)
        self.assertEqual(pkt[40], sum(pkt[1:40]) % 256)

    def test_gpu_page_last_slot_is_mhz(self):
        pkt = build_packet("gpu", False, _reading())
        self.assertEqual(pkt[6], 4)
        self.assertEqual(int.from_bytes(pkt[19:21], "big"), 11)
        self.assertEqual(pkt[25], 2)
        self.assertEqual(int.from_bytes(pkt[26:28], "big"), 1800)

    def test_psu_page_carries_estimated_watts_only(self):
        pkt = build_packet("psu", False, _reading())
        self.assertEqual(pkt[6], 5)
        self.assertEqual(int.from_bytes(pkt[28:30], "big"), 91)
        self.assertEqual(pkt[34], 18)
        self.assertEqual(struct.unpack(">f", pkt[30:34])[0], 0)
        self.assertEqual(int.from_bytes(pkt[37:39], "big"), 0)

    def test_fahrenheit_flag(self):
        pkt = build_packet("cpu", True, _reading())
        self.assertEqual(pkt[9], 1)
        self.assertEqual(struct.unpack(">f", pkt[10:14])[0], 140)


class SensorMathTests(unittest.TestCase):
    def test_busy_is_whole_chip_not_one_core(self):
        # Aggregate counters: 200 busy ticks, 800 idle ticks -> 20% of the chip.
        prev = [0, 0, 0, 0, 0, 0, 0, 0]
        curr = [200, 0, 0, 800, 0, 0, 0, 0]
        self.assertEqual(busy_percent(prev, curr), 20)

    def test_rapl_delta_is_watts(self):
        self.assertEqual(watts_from_uj(1_000_000, 81_000_000, 1.0, None), 80)

    def test_gated_gpu_uses_idle_step(self):
        starred, levels = parse_dpm_sclk("S: 0Mhz *\n1: 500Mhz \n2: 2520Mhz \n")
        self.assertEqual(starred, 0)
        self.assertEqual(choose_gfx_mhz(0, starred, levels, "lowest_step"), 500)
        self.assertEqual(choose_gfx_mhz(0, starred, levels, "zero"), 0)

    def test_live_metrics_clock_wins(self):
        self.assertEqual(choose_gfx_mhz(1876, 0, [0, 500, 2520], "lowest_step"), 1876)

    def test_metrics_layout_matches_uclk_slot(self):
        buf = bytearray(120)
        struct.pack_into("<HBB", buf, 0, 120, 1, 3)
        struct.pack_into("<H", buf, 54, 1876)
        struct.pack_into("<H", buf, 58, 96)
        parsed = parse_gpu_metrics(bytes(buf))
        self.assertEqual(parsed["gfx_mhz"], 1876)
        self.assertEqual(parsed["uclk_mhz"], 96)

    def test_config_rejects_garbage_pages(self):
        cfg = Config(mode="nope", pages="cpu", fahrenheit="false", dwell_sec=0)
        clean = cfg.normalized()
        self.assertEqual(clean.mode, "auto")
        self.assertEqual(clean.pages, ["cpu", "gpu"])
        self.assertFalse(clean.fahrenheit)
        self.assertEqual(clean.dwell_sec, 1)


if __name__ == "__main__":
    unittest.main()

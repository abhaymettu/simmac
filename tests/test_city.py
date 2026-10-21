import os
import unittest
from unittest import mock

from simmac.city import Sampler, group_apps
from simmac.sources import Raw, parse_ps

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def raw(rx=0, tx=0):
    with open(os.path.join(FIX, "ps.txt")) as f:
        procs = parse_ps(f.read())
    return Raw(procs=procs, vm={"active": 4 * 2 ** 30, "wired": 2 * 2 ** 30, "compressed": 2 ** 30},
               net_rx=rx, net_tx=tx, load=[3.0, 2.0, 1.0], ncpu=4, mem_total=16 * 2 ** 30)


class GroupAppsTest(unittest.TestCase):
    def test_one_building_per_app_with_sums(self):
        apps = {a["name"]: a for a in group_apps(raw())}
        chrome = apps["Google Chrome"]
        self.assertEqual(chrome["procs"], 2)
        self.assertEqual(chrome["cpu"], 55.5)
        self.assertEqual(chrome["mem_mb"], 800.0)
        self.assertEqual(chrome["district"], "apps")
        self.assertEqual(len(apps), 9)

    def test_sorted_by_memory_and_limited(self):
        apps = group_apps(raw(), limit=3)
        self.assertEqual([a["name"] for a in apps], ["Google Chrome", "claude", "postgres"])

    def test_redaction_renames_matching_apps(self):
        with mock.patch.dict(os.environ, {"SIMMAC_REDACT": "chrome, POSTGRES"}):
            names = {a["name"] for a in group_apps(raw())}
        self.assertNotIn("Google Chrome", names)
        self.assertNotIn("postgres", names)
        self.assertIn("private", names)


class SamplerTest(unittest.TestCase):
    def test_network_rate_from_counter_deltas(self):
        s = Sampler()
        first = s.snapshot(raw(1000, 500), now=100.0)
        self.assertEqual(first["net"], {"rx_bps": 0, "tx_bps": 0})
        second = s.snapshot(raw(5000, 1500), now=102.0)
        self.assertEqual(second["net"], {"rx_bps": 2000, "tx_bps": 500})

    def test_counter_reset_never_goes_negative(self):
        s = Sampler()
        s.snapshot(raw(5000, 5000), now=1.0)
        snap = s.snapshot(raw(10, 10), now=2.0)
        self.assertEqual(snap["net"], {"rx_bps": 0, "tx_bps": 0})

    def test_cpu_memory_and_counts(self):
        snap = Sampler().snapshot(raw(), now=0.0)
        total_cpu = 0.6 + 12.5 + 1.0 + 3.2 + 20.0 + 35.5 + 0.1 + 62.3
        self.assertAlmostEqual(snap["cpu"], round(total_cpu / 400.0, 4))
        self.assertEqual(snap["mem"], {"total_gb": 16.0, "used": 0.4375})
        self.assertEqual(snap["procs"], 10)
        self.assertEqual(snap["load"], [3.0, 2.0, 1.0])
        self.assertTrue(0 <= snap["hour"] < 24)


if __name__ == "__main__":
    unittest.main()

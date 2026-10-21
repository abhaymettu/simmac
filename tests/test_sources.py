import os
import unittest

from simmac.sources import (app_name, district, memory_used_fraction, parse_loadavg,
                            parse_netstat_ib, parse_ps, parse_vm_stat)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return f.read()


class PsTest(unittest.TestCase):
    def test_parses_rows_and_skips_bad_lines(self):
        procs = parse_ps(fixture("ps.txt"))
        self.assertEqual(len(procs), 10)
        first = procs[0]
        self.assertEqual((first.pid, first.ppid, first.cpu, first.mem_pct, first.rss_kb, first.command),
                         (1, 0, 0.6, 0.1, 25376, "/sbin/launchd"))
        self.assertEqual(procs[6].command.split("/")[-1], "Google Chrome Helper (Renderer)")

    def test_app_name_groups_helpers_under_the_outer_app(self):
        procs = parse_ps(fixture("ps.txt"))
        names = [app_name(p.command) for p in procs]
        self.assertEqual(names, ["launchd", "claude", "intentd", "npm", "node", "Google Chrome",
                                 "Google Chrome", "Finder", "logd", "postgres"])

    def test_app_name_keeps_only_the_base_name_of_relative_paths(self):
        self.assertEqual(app_name(".venv/bin/python"), "python")
        self.assertEqual(app_name("./node_modules/.bin/vite --port 3000"), "vite")
        self.assertEqual(app_name("scripts/run.sh"), "run.sh")
        self.assertEqual(app_name("postgres: writer"), "postgres")
        self.assertEqual(app_name("python3"), "python3")

    def test_district(self):
        self.assertEqual(district("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "apps")
        self.assertEqual(district("/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"), "system")
        self.assertEqual(district("/usr/libexec/logd"), "system")
        self.assertEqual(district("/sbin/launchd"), "system")
        self.assertEqual(district("node"), "workshop")
        self.assertEqual(district("/Users/someone/.local/bin/claude"), "workshop")


class VmStatTest(unittest.TestCase):
    def test_reads_page_size_and_counts(self):
        vm = parse_vm_stat(fixture("vm_stat.txt"))
        self.assertEqual(vm["free"], 21939 * 16384)
        self.assertEqual(vm["active"], 309448 * 16384)
        self.assertEqual(vm["wired"], 403478 * 16384)
        self.assertEqual(vm["compressed"], 401876 * 16384)

    def test_used_fraction(self):
        vm = {"active": 2, "wired": 1, "compressed": 1, "free": 4}
        self.assertAlmostEqual(memory_used_fraction(vm, 8), 0.5)
        self.assertEqual(memory_used_fraction(vm, 0), 0.0)
        self.assertEqual(memory_used_fraction({"active": 20}, 8), 1.0)


class NetstatTest(unittest.TestCase):
    def test_sums_link_rows_of_physical_interfaces_once(self):
        rx, tx = parse_netstat_ib(fixture("netstat_ib.txt"))
        # en0 once (its address rows repeat the counters) plus awdl0; loopback,
        # tunnels, bridge and anpi are skipped.
        self.assertEqual(rx, 133258984141 + 20000)
        self.assertEqual(tx, 19988087361 + 30000)

    def test_empty_input(self):
        self.assertEqual(parse_netstat_ib(""), (0, 0))


class LoadTest(unittest.TestCase):
    def test_loadavg(self):
        self.assertEqual(parse_loadavg("{ 9.67 6.93 5.92 }\n"), [9.67, 6.93, 5.92])
        self.assertEqual(parse_loadavg(""), [0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()

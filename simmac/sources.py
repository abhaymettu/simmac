"""Read and parse real system data on macOS using only built-in commands.

Every parser is a pure function from command output text to plain data, so the
tests can feed recorded output. The read_* functions run the commands.
"""
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

PS_ARGS = ["ps", "-axo", "pid=,ppid=,pcpu=,pmem=,rss=,comm="]

# Interfaces whose bytes are skipped: loopback, tunnels that re-carry traffic
# already counted on a physical interface, and links that never carry user data.
SKIP_IFACE_PREFIXES = ("lo", "utun", "gif", "stf", "bridge", "XHC", "anpi", "ipsec")


@dataclass
class Proc:
    pid: int
    ppid: int
    cpu: float  # percent of one core, as ps reports it (a decaying average)
    mem_pct: float
    rss_kb: int
    command: str


def parse_ps(text: str) -> List[Proc]:
    procs = []
    for line in text.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            procs.append(Proc(int(parts[0]), int(parts[1]), float(parts[2]),
                              float(parts[3]), int(parts[4]), parts[5].strip()))
        except ValueError:
            continue
    return procs


_APP_RE = re.compile(r"/([^/]+)\.app(?:/|$)")


def app_name(command: str) -> str:
    """Name the building a process belongs to.

    Helpers inside an app bundle group under the outermost app, so every
    "Google Chrome Helper" lands in the Google Chrome building. Other
    processes use the executable's base name with any arguments dropped.
    """
    m = _APP_RE.search(command)
    if m:
        return m.group(1)
    if command.startswith("/"):
        return command.rstrip("/").rsplit("/", 1)[-1] or command
    first = command.split()[0] if command.split() else command
    # A relative path like ".venv/bin/python" keeps only its base name, so no
    # local directory reaches the page.
    first = first.rstrip("/").rsplit("/", 1)[-1] or first
    # Process titles like "postgres: writer" name the program before the colon.
    return first.rstrip(":") or first


def district(command: str) -> str:
    """Which part of town: apps, system, or the workshop (developer tools)."""
    if _APP_RE.search(command):
        if command.startswith("/System/"):
            return "system"
        return "apps"
    if command.startswith(("/System/", "/usr/libexec/", "/usr/sbin/", "/sbin/",
                           "/Library/Apple/")) or command in ("launchd", "kernel_task"):
        return "system"
    return "workshop"


def parse_vm_stat(text: str) -> Dict[str, int]:
    """Return bytes for free, active, inactive, speculative, wired, compressed."""
    m = re.search(r"page size of (\d+) bytes", text)
    page = int(m.group(1)) if m else 4096
    keys = {
        "Pages free": "free",
        "Pages active": "active",
        "Pages inactive": "inactive",
        "Pages speculative": "speculative",
        "Pages wired down": "wired",
        "Pages occupied by compressor": "compressed",
    }
    out = {v: 0 for v in keys.values()}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().strip('"')
        if k in keys:
            try:
                out[keys[k]] = int(v.strip().rstrip(".")) * page
            except ValueError:
                pass
    return out


def memory_used_fraction(vm: Dict[str, int], total_bytes: int) -> float:
    """Approximate Activity Monitor's "memory used": app (active) + wired + compressed."""
    if total_bytes <= 0:
        return 0.0
    used = vm.get("active", 0) + vm.get("wired", 0) + vm.get("compressed", 0)
    return max(0.0, min(1.0, used / total_bytes))


def parse_netstat_ib(text: str) -> Tuple[int, int]:
    """Total received and sent bytes across physical interfaces.

    Only the <Link#n> row of each interface is used, since the address rows
    repeat the same counters. The Address column can be empty, so the numbers
    are read from the right: Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll.
    """
    rx = tx = 0
    seen = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10 or "<Link#" not in line:
            continue
        name = parts[0].rstrip("*")
        if name in seen or name.startswith(SKIP_IFACE_PREFIXES):
            continue
        tail = parts[-7:]
        try:
            ib, ob = int(tail[2]), int(tail[5])
        except ValueError:
            continue
        seen.add(name)
        rx += ib
        tx += ob
    return rx, tx


def parse_loadavg(text: str) -> List[float]:
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    return [float(n) for n in nums[:3]] if len(nums) >= 3 else [0.0, 0.0, 0.0]


def _run(args: List[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _sysctl_int(name: str) -> Optional[int]:
    out = _run(["sysctl", "-n", name]).strip()
    return int(out) if out.isdigit() else None


@dataclass
class Raw:
    procs: List[Proc]
    vm: Dict[str, int]
    net_rx: int
    net_tx: int
    load: List[float]
    ncpu: int
    mem_total: int


def read_raw() -> Raw:
    rx, tx = parse_netstat_ib(_run(["netstat", "-ib"]))
    return Raw(
        procs=parse_ps(_run(PS_ARGS)),
        vm=parse_vm_stat(_run(["vm_stat"])),
        net_rx=rx,
        net_tx=tx,
        load=parse_loadavg(_run(["sysctl", "-n", "vm.loadavg"])),
        ncpu=_sysctl_int("hw.ncpu") or 1,
        mem_total=_sysctl_int("hw.memsize") or 0,
    )

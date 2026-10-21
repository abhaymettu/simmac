"""Turn raw system readings into the city snapshot the page draws."""
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .sources import Raw, app_name, district, memory_used_fraction

MAX_BUILDINGS = 60


def _redactions() -> List[str]:
    raw = os.environ.get("SIMMAC_REDACT", "")
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def group_apps(raw: Raw, limit: int = MAX_BUILDINGS) -> List[dict]:
    """One building per app: summed CPU and memory, and how many processes it runs."""
    redact = _redactions()
    apps: Dict[str, dict] = {}
    for p in raw.procs:
        name = app_name(p.command)
        if any(w in name.lower() for w in redact):
            name = "private"
        a = apps.get(name)
        if a is None:
            a = apps[name] = {"name": name, "district": district(p.command),
                              "cpu": 0.0, "mem_mb": 0.0, "procs": 0}
        a["cpu"] += p.cpu
        a["mem_mb"] += p.rss_kb / 1024.0
        a["procs"] += 1
    ranked = sorted(apps.values(), key=lambda a: (-a["mem_mb"], a["name"]))[:limit]
    for a in ranked:
        a["cpu"] = round(a["cpu"], 1)
        a["mem_mb"] = round(a["mem_mb"], 1)
    return ranked


@dataclass
class Sampler:
    """Keeps the previous network counters so it can report bytes per second."""
    last_net: Optional[tuple] = None
    last_t: Optional[float] = None
    history: List[float] = field(default_factory=list)

    def snapshot(self, raw: Raw, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        rx_bps = tx_bps = 0.0
        if self.last_net is not None and self.last_t is not None and now > self.last_t:
            dt = now - self.last_t
            # Counters can reset (an interface going away); never report negative traffic.
            rx_bps = max(0.0, (raw.net_rx - self.last_net[0]) / dt)
            tx_bps = max(0.0, (raw.net_tx - self.last_net[1]) / dt)
        self.last_net = (raw.net_rx, raw.net_tx)
        self.last_t = now
        cpu_sum = sum(p.cpu for p in raw.procs)
        cpu_frac = min(1.0, cpu_sum / (100.0 * max(1, raw.ncpu)))
        lt = time.localtime(now)
        return {
            "t": now,
            "hour": lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0,
            "ncpu": raw.ncpu,
            "load": raw.load,
            "cpu": round(cpu_frac, 4),
            "mem": {
                "total_gb": round(raw.mem_total / 2 ** 30, 1),
                "used": round(memory_used_fraction(raw.vm, raw.mem_total), 4),
            },
            "net": {"rx_bps": round(rx_bps), "tx_bps": round(tx_bps)},
            "procs": len(raw.procs),
            "apps": group_apps(raw),
        }

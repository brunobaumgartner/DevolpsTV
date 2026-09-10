"""Consumo de recursos do servidor, lido direto de /proc (sem dependência
extra). Dentro do container o /proc de CPU e memória reflete o HOST — que é
justamente o que queremos mostrar na tela "Sistema" do admin.
"""

import os
import shutil
import time


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def _cpu_times():
    line = _read("/proc/stat").splitlines()
    if not line or not line[0].startswith("cpu "):
        return None
    parts = [int(x) for x in line[0].split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)  # idle + iowait
    total = sum(parts)
    return total, idle


def cpu_percent(sample: float = 0.25) -> float | None:
    a = _cpu_times()
    if a is None:
        return None
    time.sleep(sample)
    b = _cpu_times()
    dt = b[0] - a[0]
    di = b[1] - a[1]
    if dt <= 0:
        return None
    return round(100.0 * (1.0 - di / dt), 1)


def _meminfo() -> dict:
    out = {}
    for ln in _read("/proc/meminfo").splitlines():
        k, _, rest = ln.partition(":")
        v = rest.strip().split()
        if v and v[0].isdigit():
            out[k] = int(v[0]) * 1024  # kB -> bytes
    return out


def snapshot() -> dict:
    mi = _meminfo()
    total = mi.get("MemTotal", 0)
    avail = mi.get("MemAvailable", 0)
    used = total - avail if total else 0

    swap_total = mi.get("SwapTotal", 0)
    swap_free = mi.get("SwapFree", 0)

    load = _read("/proc/loadavg").split()[:3]
    ncpu = os.cpu_count() or 1

    try:
        up = float(_read("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        up = None

    # disco: o bind-mount /app/data aponta pro /srv/iptv/data do host, então
    # reflete o disco real do servidor (o "/" do container é o overlay efêmero)
    disk_path = "/app/data" if os.path.isdir("/app/data") else "/"
    du = shutil.disk_usage(disk_path)

    return {
        "cpu_percent": cpu_percent(),
        "cpu_count": ncpu,
        "load_avg": [float(x) for x in load] if len(load) == 3 else None,
        "mem_total": total,
        "mem_used": used,
        "mem_percent": round(100.0 * used / total, 1) if total else None,
        "swap_total": swap_total,
        "swap_used": swap_total - swap_free,
        "disk_total": du.total,
        "disk_used": du.used,
        "disk_percent": round(100.0 * du.used / du.total, 1) if du.total else None,
        "uptime_seconds": up,
        "sampled_at": time.time(),
    }

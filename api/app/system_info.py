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


def _pid_cpu_ticks(pid: str) -> int | None:
    stat = _read(f"/proc/{pid}/stat")
    if not stat:
        return None
    # campos 14 (utime) e 15 (stime) de /proc/pid/stat, em jiffies — o comm
    # (campo 2) pode ter espaço/parênteses, então localiza pelo último ")"
    # antes de separar o resto (o que sobra começa no campo 3 = índice 0)
    tail = stat[stat.rfind(")") + 1 :].split()
    try:
        return int(tail[11]) + int(tail[12])  # campos 14 e 15 = índices 11 e 12 depois do corte
    except (IndexError, ValueError):
        return None


def _pid_cmdline(pid: str) -> str | None:
    raw = _read(f"/proc/{pid}/cmdline")
    if not raw:
        # kernel thread ou processo sem cmdline (zumbi) — usa o comm entre parênteses do stat
        stat = _read(f"/proc/{pid}/stat")
        if stat and "(" in stat and ")" in stat:
            return "[" + stat[stat.find("(") + 1 : stat.rfind(")")] + "]"
        return None
    return raw.replace("\x00", " ").strip() or None


def _pid_rss_bytes(pid: str) -> int:
    for ln in _read(f"/proc/{pid}/status").splitlines():
        if ln.startswith("VmRSS:"):
            parts = ln.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return 0


def top_processes(limit: int = 12, sample: float = 0.3) -> list[dict]:
    """Processos visíveis DENTRO do container da API (mesmo namespace de PID),
    ordenados por CPU — inclui a própria API e qualquer `docker exec` rodando
    aqui dentro (ex: importações de CSV via CLI), que não aparecem na lista de
    jobs (essa só rastreia o que foi disparado pela tela web). NÃO enxerga
    outros containers (mysql, worker) — isolamento normal de PID namespace,
    sem `pid: host` no compose (decisão deliberada, ver ARQUITETURA.md)."""
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return []

    clk_tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    before = {p: _pid_cpu_ticks(p) for p in pids}
    time.sleep(sample)

    rows = []
    for p in pids:
        after = _pid_cpu_ticks(p)
        b = before.get(p)
        if after is None or b is None or after < b:
            continue
        cpu_pct = round(100.0 * ((after - b) / clk_tck) / sample, 1)
        cmd = _pid_cmdline(p)
        if not cmd:
            continue
        rows.append({"pid": int(p), "cmd": cmd[:200], "cpu_percent": cpu_pct, "mem_bytes": _pid_rss_bytes(p)})

    rows.sort(key=lambda r: -r["cpu_percent"])
    return rows[:limit]


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

import os
import re
import subprocess
import sys

from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort

_SUBPROCESS_TIMEOUT = 2
_SWAP_RE = re.compile(r"total\s*=\s*([\d.]+)M\s+used\s*=\s*([\d.]+)M")


def _run(argv):
    try:
        result = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def _process_group_rss_kb(argv):
    out = _run(argv)
    if out is None:
        return 0
    total = 0
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            total += int(line)
        except ValueError:
            continue
    return total


def _pool_rss_kb(workers, rss_argv_for):
    total = 0
    for w in workers:
        if w.pid is None:
            continue
        try:
            pgid = os.getpgid(int(w.pid))
        except (OSError, ValueError, TypeError):
            continue
        total += _process_group_rss_kb(rss_argv_for(pgid))
    return total


def _macos_swap_pressure():
    out = _run(["sysctl", "-n", "vm.swapusage"])
    if out is None:
        return None
    match = _SWAP_RE.search(out)
    if not match:
        return None
    total, used = float(match.group(1)), float(match.group(2))
    return (used / total) if total > 0 else 0.0


def _macos_total_memory_kb():
    out = _run(["sysctl", "-n", "hw.memsize"])
    if out is None:
        return None
    try:
        return int(out.strip()) / 1024
    except ValueError:
        return None


def _headroom_macos(workers):
    pressure = _macos_swap_pressure()
    total_mem_kb = _macos_total_memory_kb()
    if pressure is None or not total_mem_kb:
        return MachineHeadroom(system_pressure=None, pool_share=None)
    pool_rss_kb = _pool_rss_kb(workers, lambda pgid: ["ps", "-o", "rss=", "-g", str(pgid)])
    return MachineHeadroom(system_pressure=pressure, pool_share=pool_rss_kb / total_mem_kb)


def _proc_meminfo():
    try:
        with open("/proc/meminfo") as f:
            text = f.read()
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        try:
            values[key.strip()] = float(rest.strip().split()[0])
        except (ValueError, IndexError):
            continue
    return values


def _linux_swap_pressure(meminfo):
    total = meminfo.get("SwapTotal")
    free = meminfo.get("SwapFree")
    if total is None or free is None:
        return None
    return ((total - free) / total) if total > 0 else 0.0


def _headroom_linux(workers):
    meminfo = _proc_meminfo()
    total_mem_kb = meminfo.get("MemTotal") if meminfo else None
    pressure = _linux_swap_pressure(meminfo) if meminfo else None
    if pressure is None or not total_mem_kb:
        return MachineHeadroom(system_pressure=None, pool_share=None)
    pool_rss_kb = _pool_rss_kb(workers, lambda pgid: ["ps", "-o", "rss=", "--pgid", str(pgid)])
    return MachineHeadroom(system_pressure=pressure, pool_share=pool_rss_kb / total_mem_kb)


class MachineAdapter(MachinePort):
    def headroom(self, workers):
        if sys.platform == "darwin":
            return _headroom_macos(workers)
        if sys.platform == "linux":
            return _headroom_linux(workers)
        return MachineHeadroom(system_pressure=None, pool_share=None)

    def self_rss(self):
        out = _run(["ps", "-o", "rss=", "-p", str(os.getpid())])
        if out is None:
            return None
        try:
            return int(out.strip())
        except ValueError:
            return None

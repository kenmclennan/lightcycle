import os
import re
import subprocess
import sys

from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort

_SUBPROCESS_TIMEOUT = 2
_VM_STAT_PAGE_SIZE_RE = re.compile(r"page size of (\d+) bytes")
_VM_STAT_COMPRESSOR_RE = re.compile(r"Pages occupied by compressor:\s*(\d+)\.")
_PSI_AVG10_RE = re.compile(r"avg10=([\d.]+)")


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


def _macos_memory_pressure(total_mem_kb):
    if not total_mem_kb:
        return None
    out = _run(["vm_stat"])
    if out is None:
        return None
    page_size_match = _VM_STAT_PAGE_SIZE_RE.search(out)
    compressor_match = _VM_STAT_COMPRESSOR_RE.search(out)
    if not page_size_match or not compressor_match:
        return None
    page_size = int(page_size_match.group(1))
    compressor_pages = int(compressor_match.group(1))
    compressor_kb = (compressor_pages * page_size) / 1024
    return compressor_kb / total_mem_kb


def _macos_total_memory_kb():
    out = _run(["sysctl", "-n", "hw.memsize"])
    if out is None:
        return None
    try:
        return int(out.strip()) / 1024
    except ValueError:
        return None


def _headroom_macos(workers):
    total_mem_kb = _macos_total_memory_kb()
    pool_share = None
    if total_mem_kb:
        pool_rss_kb = _pool_rss_kb(workers, lambda pgid: ["ps", "-o", "rss=", "-g", str(pgid)])
        pool_share = pool_rss_kb / total_mem_kb
    return MachineHeadroom(system_pressure=_macos_memory_pressure(total_mem_kb), pool_share=pool_share)


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


def _linux_memory_pressure():
    try:
        with open("/proc/pressure/memory") as f:
            text = f.read()
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("full "):
            match = _PSI_AVG10_RE.search(line)
            if match:
                return float(match.group(1)) / 100.0
    return None


def _headroom_linux(workers):
    meminfo = _proc_meminfo()
    total_mem_kb = meminfo.get("MemTotal") if meminfo else None
    pool_share = None
    if total_mem_kb:
        pool_rss_kb = _pool_rss_kb(workers, lambda pgid: ["ps", "-o", "rss=", "--pgid", str(pgid)])
        pool_share = pool_rss_kb / total_mem_kb
    return MachineHeadroom(system_pressure=_linux_memory_pressure(), pool_share=pool_share)


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

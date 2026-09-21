import json
import os
import re
import subprocess
import sys
import tempfile

from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort

_SUBPROCESS_TIMEOUT = 2
_SMAPS_PSS_RE = re.compile(r"^Pss:\s*(\d+) kB", re.MULTILINE)
_SMAPS_SWAP_PSS_RE = re.compile(r"^SwapPss:\s*(\d+) kB", re.MULTILINE)
_STATUS_VM_HWM_RE = re.compile(r"^VmHWM:\s*(\d+) kB", re.MULTILINE)


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


def _worker_pids(workers, pid_argv_for):
    groups = []
    for w in workers:
        if w.pid is None:
            continue
        try:
            pgid = os.getpgid(int(w.pid))
        except (OSError, ValueError, TypeError):
            pgid = int(w.pid)
        out = _run(pid_argv_for(pgid))
        pids = []
        if out is not None:
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    pids.append(int(line))
                except ValueError:
                    continue
        groups.append(pids)
    return groups


def _macos_footprint_kb(pids):
    if not pids:
        return {}
    fd, path = tempfile.mkstemp(prefix="lc-footprint-", suffix=".json")
    os.close(fd)
    try:
        argv = ["footprint", "--noCategories", "-j", path] + [str(p) for p in pids]
        if _run(argv) is None:
            return None
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        result = {}
        for proc in data.get("processes") or []:
            aux = proc.get("auxiliary") or {}
            pid = proc.get("pid")
            current = aux.get("phys_footprint")
            peak = aux.get("phys_footprint_peak")
            if pid is None or current is None or peak is None:
                continue
            result[pid] = (current / 1024.0, peak / 1024.0)
        return result
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _macos_pool_footprint_kb(workers):
    if not workers:
        return (0.0, None)
    groups = _worker_pids(workers, lambda pgid: ["ps", "-o", "pid=", "-g", str(pgid)])
    all_pids = [pid for g in groups for pid in g]
    if not all_pids:
        return (None, None)
    readings = _macos_footprint_kb(all_pids)
    if not readings:
        return (None, None)
    worker_current_kb = []
    worker_peak_kb = []
    for g in groups:
        if not g:
            continue
        worker_current_kb.append(sum(readings.get(p, (0.0, 0.0))[0] for p in g))
        worker_peak_kb.append(sum(readings.get(p, (0.0, 0.0))[1] for p in g))
    pool_kb = sum(worker_current_kb)
    peak_kb = max(worker_peak_kb) if worker_peak_kb else None
    return (pool_kb, peak_kb)


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
    peak_worker_share = None
    if total_mem_kb:
        pool_kb, peak_kb = _macos_pool_footprint_kb(workers)
        if pool_kb is not None:
            pool_share = pool_kb / total_mem_kb
        if peak_kb is not None:
            peak_worker_share = peak_kb / total_mem_kb
    return MachineHeadroom(
        pool_share=pool_share,
        peak_worker_share=peak_worker_share,
    )


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


def _smaps_rollup_pss_kb(pid):
    try:
        with open("/proc/%d/smaps_rollup" % pid) as f:
            text = f.read()
    except OSError:
        return None
    pss_match = _SMAPS_PSS_RE.search(text)
    if not pss_match:
        return None
    swap_pss_match = _SMAPS_SWAP_PSS_RE.search(text)
    swap_pss_kb = float(swap_pss_match.group(1)) if swap_pss_match else 0.0
    return float(pss_match.group(1)) + swap_pss_kb


def _status_vm_hwm_kb(pid):
    try:
        with open("/proc/%d/status" % pid) as f:
            text = f.read()
    except OSError:
        return None
    match = _STATUS_VM_HWM_RE.search(text)
    return float(match.group(1)) if match else None


def _linux_pid_footprint_kb(pid):
    current_kb = _smaps_rollup_pss_kb(pid)
    if current_kb is None:
        return None
    return (current_kb, _status_vm_hwm_kb(pid))


def _linux_pool_footprint_kb(workers):
    if not workers:
        return (0.0, None)
    groups = _worker_pids(workers, lambda pgid: ["ps", "-o", "pid=", "--pgid", str(pgid)])
    all_pids = [pid for g in groups for pid in g]
    if not all_pids:
        return (None, None)
    readings = {}
    for pid in all_pids:
        reading = _linux_pid_footprint_kb(pid)
        if reading is not None:
            readings[pid] = reading
    if not readings:
        return (None, None)
    worker_current_kb = []
    worker_peak_kb = []
    for g in groups:
        if not g:
            continue
        worker_current_kb.append(sum(readings.get(p, (0.0, 0.0))[0] for p in g))
        worker_peak_kb.append(sum((readings.get(p, (0.0, 0.0))[1] or 0.0) for p in g))
    pool_kb = sum(worker_current_kb)
    peak_kb = max(worker_peak_kb) if worker_peak_kb else None
    return (pool_kb, peak_kb)


def _headroom_linux(workers):
    meminfo = _proc_meminfo()
    total_mem_kb = meminfo.get("MemTotal") if meminfo else None
    pool_share = None
    peak_worker_share = None
    if total_mem_kb:
        pool_kb, peak_kb = _linux_pool_footprint_kb(workers)
        if pool_kb is not None:
            pool_share = pool_kb / total_mem_kb
        if peak_kb is not None:
            peak_worker_share = peak_kb / total_mem_kb
    return MachineHeadroom(
        pool_share=pool_share,
        peak_worker_share=peak_worker_share,
    )


class MachineAdapter(MachinePort):
    def headroom(self, workers):
        if sys.platform == "darwin":
            return _headroom_macos(workers)
        if sys.platform == "linux":
            return _headroom_linux(workers)
        return MachineHeadroom(pool_share=None, peak_worker_share=None)

    def self_rss(self):
        out = _run(["ps", "-o", "rss=", "-p", str(os.getpid())])
        if out is None:
            return None
        try:
            return int(out.strip())
        except ValueError:
            return None

    def worktree_pids(self, path):
        out = _run(["lsof", "+D", path, "-Fp"])
        if out is None:
            return []
        pids = []
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("p"):
                continue
            try:
                pids.append(int(line[1:]))
            except ValueError:
                continue
        return pids

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager

from lightcycle.adapters.process_group import run_in_group
from lightcycle.adapters import step_scratch
from lightcycle.domain.pool.worker import Worker
from lightcycle.domain.work.worker_log import gh_calls_filename
from lightcycle.ports.workers import RegistryUnreadable, WorkersPort


def workers_path(root):
    return os.path.join(root, "logs", "workers.json")


def _lock_path(root):
    return os.path.join(root, "logs", "workers.lock")


@contextmanager
def registry_lock(root):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    fd = os.open(_lock_path(root), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def workers_state(root):
    p = workers_path(root)
    if not os.path.exists(p):
        return []
    try:
        with open(p) as f:
            return json.loads(f.read())
    except Exception as e:
        sys.stderr.write("warning: could not read worker registry %s: %s\n" % (p, e))
        raise RegistryUnreadable(str(e)) from e


def write_workers(root, workers):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = workers_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(workers, indent=2))
    os.replace(tmp, p)


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False


PS_TIMEOUT_SECONDS = 5


def process_start_time(pid):
    try:
        out = run_in_group(
            ["ps", "-o", "lstart=", "-p", str(int(pid))],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PS_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    text = out.stdout.decode().strip()
    return text or None


def decide_alive(pid_exists, recorded_start, live_start):
    if not pid_exists:
        return False
    if recorded_start is None or live_start is None:
        return True
    return live_start == recorded_start


def worker_alive(pid, recorded_start):
    if not pid_alive(pid):
        return False
    return decide_alive(True, recorded_start, process_start_time(pid))


_TRACKED_CHILDREN = {}


def track_child(proc):
    _TRACKED_CHILDREN[proc.pid] = proc


def reap_children():
    for pid, proc in list(_TRACKED_CHILDREN.items()):
        if proc.poll() is not None:
            _TRACKED_CHILDREN.pop(pid, None)


def _signal_group(pid, sig):
    try:
        pid = int(pid)
        own_pgid = os.getpgid(0)
        try:
            pgid = os.getpgid(pid)
        except (OSError, ValueError, TypeError):
            pgid = pid
        if pgid == own_pgid:
            os.kill(pid, sig)
        else:
            os.killpg(pgid, sig)
    except (OSError, ValueError, TypeError):
        pass


def kill(pid):
    _signal_group(pid, signal.SIGCONT)
    _signal_group(pid, signal.SIGTERM)


def register_worker(root, entry):
    with registry_lock(root):
        workers = workers_state(root)
        workers.append(entry)
        write_workers(root, workers)


def reap_worker_group(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid_alive(pid):
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError):
        return False
    return True


def group_alive(pgid):
    try:
        os.killpg(int(pgid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def kill_worker_group(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid_alive(pid):
        return False
    for sig in (signal.SIGCONT, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except (OSError, ValueError):
            return False
    return True


def _end_group(entry, grace_seconds, now):
    pid = entry.get("pid", -1)
    if not group_alive(pid):
        return False, False
    term_at = entry.get("reap_term_at")
    if term_at is None:
        reap_worker_group(pid)
        entry["reap_term_at"] = now
        return True, True
    if now - term_at >= grace_seconds:
        kill_worker_group(pid)
    return True, False


def _signal_for(action, pids, signaller):
    if action == "term":
        signaller(pids, signal.SIGTERM)
    elif action == "kill":
        signaller(pids, signal.SIGKILL)


def _reap_entry_scratch(entry, folder, tagged, group_live, grace_seconds, stamp, signaller):
    pids = [] if tagged is None else tagged.get(folder, [])
    action = step_scratch.reap_scratch(entry.get("scratch_term_at"), None if tagged is None else pids, group_live, grace_seconds, stamp)
    touched = False
    if action in ("term", "kill"):
        _signal_for(action, pids, signaller)
        if action == "term":
            entry["scratch_term_at"] = stamp
            touched = True
    elif action == "delete":
        shutil.rmtree(folder, ignore_errors=True)
    done = action == "delete" and not os.path.exists(folder)
    return done, touched


def _reap_stray(folder, tagged, grace_seconds, stamp, signaller):
    if tagged is None:
        return
    pids = tagged.get(folder, [])
    term_at = step_scratch.read_marker(folder)
    action = step_scratch.reap_scratch(term_at, pids, False, grace_seconds, stamp)
    if action == "delete":
        shutil.rmtree(folder, ignore_errors=True)
    elif action in ("term", "kill"):
        _signal_for(action, pids, signaller)
        if action == "term":
            step_scratch.write_marker(folder, stamp)


def prune_workers(
    root, keep_dead, grace_seconds=0, now=time.time, alive=worker_alive,
    tagged=step_scratch.tagged_pids, signaller=step_scratch.signal_tagged,
):
    with registry_lock(root):
        workers = workers_state(root)
        dead_idx = [
            i
            for i, w in enumerate(workers)
            if not alive(w.get("pid", -1), w.get("pid_started"))
        ]
        stamp = now()
        folders = {}
        for i in dead_idx:
            folder = step_scratch.scratch_dir(root, workers[i].get("spawnid") or "")
            if workers[i].get("spawnid") and os.path.isdir(folder):
                folders[i] = folder
        strays = step_scratch.stray_scratch_dirs(
            root, {w.get("spawnid") for w in workers}, stamp
        )
        scan = tagged(list(folders.values()) + strays) if (folders or strays) else {}
        live_groups = set()
        changed = False
        for i in dead_idx:
            live, touched = _end_group(workers[i], grace_seconds, stamp)
            if i in folders:
                done, scratch_touched = _reap_entry_scratch(
                    workers[i], folders[i], scan, live, grace_seconds, stamp, signaller
                )
                touched = touched or scratch_touched
                live = live or not done
            if live:
                live_groups.add(i)
            changed = changed or touched
        for folder in strays:
            _reap_stray(folder, scan, grace_seconds, stamp, signaller)
        n_drop = max(0, len(dead_idx) - keep_dead)
        drop = set([i for i in dead_idx if i not in live_groups][:n_drop])
        if not drop:
            if changed:
                write_workers(root, workers)
            return 0
        write_workers(root, [w for i, w in enumerate(workers) if i not in drop])
        for i in drop:
            _remove_quietly(os.path.join(root, "logs", gh_calls_filename(workers[i].get("spawnid"))))
        return len(drop)


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def prune_pool_gh_call_logs(root, keep):
    logs = os.path.join(root, "logs")
    try:
        names = sorted(
            n for n in os.listdir(logs) if n.startswith("gh-calls-pool-") and n.endswith(".log")
        )
    except OSError:
        return
    for name in names[:max(0, len(names) - max(keep, 1))]:
        _remove_quietly(os.path.join(logs, name))


def set_step(root, spawnid, step):
    with registry_lock(root):
        workers = workers_state(root)
        for w in workers:
            if w.get("spawnid") == spawnid:
                w["step"] = step
        write_workers(root, workers)


def step_for(root, spawnid):
    for w in workers_state(root):
        if w.get("spawnid") == spawnid:
            return w.get("step")
    return None


def mark_checked(root, spawnid):
    with registry_lock(root):
        workers = workers_state(root)
        for w in workers:
            if w.get("spawnid") == spawnid:
                w["checked"] = True
        write_workers(root, workers)


def mark_halted(root, spawnid):
    with registry_lock(root):
        workers = workers_state(root)
        for w in workers:
            if w.get("spawnid") == spawnid:
                w["halted"] = True
        write_workers(root, workers)


def set_pid_started(root, spawnid, pid_started):
    with registry_lock(root):
        workers = workers_state(root)
        for w in workers:
            if w.get("spawnid") == spawnid:
                w["pid_started"] = pid_started
        write_workers(root, workers)


class WorkersAdapter(WorkersPort):
    def __init__(self, config):
        self._config = config
        self._tick_memo = None

    def begin_tick(self):
        self._tick_memo = {}

    def end_tick(self):
        self._tick_memo = None

    def workers_state(self):
        return [Worker.from_state(d) for d in workers_state(self._config.data_root())]

    def pid_alive(self, pid, started=None):
        memo = self._tick_memo
        if memo is None:
            return worker_alive(pid, started)
        key = (pid, started)
        if key not in memo:
            memo[key] = worker_alive(pid, started)
        return memo[key]

    def reap(self):
        return reap_children()

    def kill(self, pid):
        if self._tick_memo is not None:
            for key in [k for k in self._tick_memo if k[0] == pid]:
                del self._tick_memo[key]
        return kill(pid)

    def prune_workers(self, keep_dead=None):
        kd = self._config.worker_history() if keep_dead is None else keep_dead
        dropped = prune_workers(
            self._config.data_root(), kd, grace_seconds=self._config.shutdown_grace_seconds(),
            alive=self.pid_alive,
        )
        prune_pool_gh_call_logs(self._config.data_root(), kd)
        return dropped

    def set_step(self, spawnid, step):
        return set_step(self._config.data_root(), spawnid, step)

    def step_for(self, spawnid):
        return step_for(self._config.data_root(), spawnid)

    def mark_checked(self, spawnid):
        return mark_checked(self._config.data_root(), spawnid)

    def mark_halted(self, spawnid):
        return mark_halted(self._config.data_root(), spawnid)

    def set_pid_started(self, spawnid, pid_started):
        return set_pid_started(self._config.data_root(), spawnid, pid_started)

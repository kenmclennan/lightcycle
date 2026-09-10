import fcntl
import json
import os
import signal
import subprocess
import sys
from contextlib import contextmanager

from lightcycle.domain.pool.worker import Worker
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
        return json.loads(open(p).read())
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
    except (OSError, ValueError, TypeError):
        return False


def process_start_time(pid):
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(int(pid))],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError, TypeError):
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
    return decide_alive(pid_alive(pid), recorded_start, process_start_time(pid))


def reap_children():
    while True:
        try:
            reaped_pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if reaped_pid == 0:
            break


def kill(pid):
    try:
        pid = int(pid)
        own_pgid = os.getpgid(0)
        try:
            pgid = os.getpgid(pid)
        except (OSError, ValueError, TypeError):
            os.kill(pid, signal.SIGTERM)
            return
        if pgid == own_pgid:
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(pgid, signal.SIGTERM)
    except (OSError, ValueError, TypeError):
        pass


def register_worker(root, entry):
    with registry_lock(root):
        workers = workers_state(root)
        workers.append(entry)
        write_workers(root, workers)


def prune_workers(root, keep_dead):
    with registry_lock(root):
        workers = workers_state(root)
        dead_idx = [
            i
            for i, w in enumerate(workers)
            if not worker_alive(w.get("pid", -1), w.get("pid_started"))
        ]
        n_drop = max(0, len(dead_idx) - keep_dead)
        if not n_drop:
            return 0
        drop = set(dead_idx[:n_drop])
        write_workers(root, [w for i, w in enumerate(workers) if i not in drop])
        return n_drop


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

    def workers_state(self):
        return [Worker.from_state(d) for d in workers_state(self._config.data_root())]

    def pid_alive(self, pid, started=None):
        return worker_alive(pid, started)

    def reap(self):
        return reap_children()

    def kill(self, pid):
        return kill(pid)

    def prune_workers(self, keep_dead=None):
        kd = self._config.worker_history() if keep_dead is None else keep_dead
        return prune_workers(self._config.data_root(), kd)

    def set_step(self, spawnid, step):
        return set_step(self._config.data_root(), spawnid, step)

    def step_for(self, spawnid):
        return step_for(self._config.data_root(), spawnid)

    def mark_checked(self, spawnid):
        return mark_checked(self._config.data_root(), spawnid)

    def set_pid_started(self, spawnid, pid_started):
        return set_pid_started(self._config.data_root(), spawnid, pid_started)

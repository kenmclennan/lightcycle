import fcntl
import json
import os
import signal
from contextlib import contextmanager

from the_grid.ports.workers import WorkersPort


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
    except Exception:
        return []


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


def kill(pid):
    try:
        os.kill(int(pid), signal.SIGTERM)
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
        dead_idx = [i for i, w in enumerate(workers) if not pid_alive(w.get("pid", -1))]
        n_drop = max(0, len(dead_idx) - keep_dead)
        if not n_drop:
            return 0
        drop = set(dead_idx[:n_drop])
        write_workers(root, [w for i, w in enumerate(workers) if i not in drop])
        return n_drop


def set_task(root, spawnid, task):
    with registry_lock(root):
        workers = workers_state(root)
        for w in workers:
            if w.get("spawnid") == spawnid:
                w["task"] = task
        write_workers(root, workers)


def mark_checked(root, spawnid):
    with registry_lock(root):
        workers = workers_state(root)
        for w in workers:
            if w.get("spawnid") == spawnid:
                w["checked"] = True
        write_workers(root, workers)


class WorkersAdapter(WorkersPort):
    def __init__(self, config):
        self._config = config

    def workers_state(self):
        return workers_state(self._config.grid_root())

    def write_workers(self, workers):
        return write_workers(self._config.grid_root(), workers)

    def pid_alive(self, pid):
        return pid_alive(pid)

    def kill(self, pid):
        return kill(pid)

    def prune_workers(self, keep_dead=None):
        kd = self._config.worker_history() if keep_dead is None else keep_dead
        return prune_workers(self._config.grid_root(), kd)

    def set_task(self, spawnid, task):
        return set_task(self._config.grid_root(), spawnid, task)

    def mark_checked(self, spawnid):
        return mark_checked(self._config.grid_root(), spawnid)

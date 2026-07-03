import json
import os

from the_grid.ports.workers import WorkersPort


def workers_path(root):
    return os.path.join(root, "logs", "workers.json")


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
    with open(workers_path(root), "w") as f:
        f.write(json.dumps(workers, indent=2))


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def prune_workers(root, keep_dead):
    workers = workers_state(root)
    dead_idx = [i for i, w in enumerate(workers) if not pid_alive(w.get("pid", -1))]
    n_drop = max(0, len(dead_idx) - keep_dead)
    if not n_drop:
        return 0
    drop = set(dead_idx[:n_drop])
    write_workers(root, [w for i, w in enumerate(workers) if i not in drop])
    return n_drop


def set_task(root, spawnid, task):
    workers = workers_state(root)
    for w in workers:
        if w.get("spawnid") == spawnid:
            w["task"] = task
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

    def prune_workers(self, keep_dead=None):
        kd = self._config.worker_history() if keep_dead is None else keep_dead
        return prune_workers(self._config.grid_root(), kd)

    def set_task(self, spawnid, task):
        return set_task(self._config.grid_root(), spawnid, task)

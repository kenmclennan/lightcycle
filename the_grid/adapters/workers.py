"""Worker run-state: the workers.json registry and pid liveness."""
import json
import os

from the_grid.adapters.fsio import grid_root
from the_grid.ports.workers import WorkersPort


def workers_path():
    return os.path.join(grid_root(), "logs", "workers.json")


def workers_state():
    p = workers_path()
    if not os.path.exists(p):
        return []
    try:
        return json.loads(open(p).read())
    except Exception:
        return []


def write_workers(workers):
    os.makedirs(os.path.join(grid_root(), "logs"), exist_ok=True)
    with open(workers_path(), "w") as f:
        f.write(json.dumps(workers, indent=2))


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def prune_workers(keep_dead=None):
    """Drop dead worker entries from the registry, keeping all live workers plus
    the most recent `keep_dead` dead ones (so tg logs can still find recently
    finished workers). Returns the number pruned."""
    if keep_dead is None:
        keep_dead = int(os.environ.get("GRID_WORKER_HISTORY", "20"))
    workers = workers_state()
    dead_idx = [i for i, w in enumerate(workers) if not pid_alive(w.get("pid", -1))]
    n_drop = max(0, len(dead_idx) - keep_dead)
    if not n_drop:
        return 0
    drop = set(dead_idx[:n_drop])
    write_workers([w for i, w in enumerate(workers) if i not in drop])
    return n_drop


def stamp_bead(spawnid, bead):
    workers = workers_state()
    for w in workers:
        if w.get("spawnid") == spawnid:
            w["bead"] = bead
    write_workers(workers)


class WorkersAdapter(WorkersPort):
    """Thin WorkersPort over the module functions."""

    def workers_state(self):
        return workers_state()

    def write_workers(self, workers):
        return write_workers(workers)

    def pid_alive(self, pid):
        return pid_alive(pid)

    def prune_workers(self, keep_dead=None):
        return prune_workers(keep_dead)

    def stamp_bead(self, spawnid, bead):
        return stamp_bead(spawnid, bead)

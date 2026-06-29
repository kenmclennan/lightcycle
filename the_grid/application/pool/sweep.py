"""Sweep: reclaim orphaned task claims and prune dead worker entries.

A task is owned by a live worker iff its assignee is the spawnid of a worker
whose pid is alive. The spawnid->pid mapping is written at spawn (before the
claim), so it never lags - a just-claimed task is protected immediately.
"""


class Sweep:

    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def execute(self):
        live = {w.get("spawnid") for w in self._workers.workers_state()
                if w.get("spawnid") and self._workers.pid_alive(w.get("pid", -1))}
        swept = []
        for bead in self._store.list_beads_by_status("in_progress"):
            if bead.get("assignee") in live:
                continue
            bid = bead["id"]
            self._store.update_status(bid, "open")
            self._store.assign(bid, "")
            swept.append(bid)
        pruned = self._workers.prune_workers()
        return {"swept": swept, "pruned": pruned}

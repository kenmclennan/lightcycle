"""Tick: one pass of the agent pool - sweep, then fill workers from the queue.

Fill up to GRID_MAX_AGENTS alive workers from the ready queue, one worker per
uncovered ready task regardless of role (bd ready already hides blocked-by tasks,
so declared dependencies are honoured for free). A worker that has spawned but
not yet claimed (bead is None) within the boot window covers a task of its role,
so the pool does not pile redundant workers onto one task. `now` is passed in
(the caller owns the clock).
"""
from the_grid.application.pool.sweep import Sweep
from the_grid.core import flow as cflow


class Tick:

    def __init__(self, store, workers, spawner, config):
        self._store = store
        self._workers = workers
        self._spawner = spawner
        self._config = config
        self._sweep = Sweep(store, workers)

    def execute(self, now):
        result = self._sweep.execute()
        result["spawned"] = []
        alive = [w for w in self._workers.workers_state()
                 if self._workers.pid_alive(w.get("pid", -1))]
        slots = self._config.max_agents() - len(alive)
        if slots <= 0:
            return result
        max_boot = self._config.max_boot_seconds()
        inflight = {}
        for w in alive:
            if w.get("bead") is None and (now - w.get("started", 0)) < max_boot:
                inflight[w["role"]] = inflight.get(w["role"], 0) + 1
        ready = cflow.ready_task_roles(self._store.ready_beads())
        for role in cflow.pool_plan(ready, inflight, slots):
            self._spawner.spawn_worker(role)
            result["spawned"].append(role)
        return result

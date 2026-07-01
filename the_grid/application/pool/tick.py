"""Tick: one pass of the agent pool - sweep, then fill workers from the queue.

Fill up to GRID_MAX_AGENTS alive workers from the ready queue, one worker per
uncovered ready task regardless of role (bd ready already hides blocked-by tasks,
so declared dependencies are honoured for free). A worker that has spawned but
not yet claimed (bead is None) within the boot window covers a task of its role,
so the pool does not pile redundant workers onto one task. `now` is passed in
(the caller owns the clock).
"""
from dataclasses import dataclass
from typing import List

from the_grid.application.pool.sweep import SweepUseCase
from the_grid.domain.pool import PoolPlan, ReadyQueue, WorkerPool


@dataclass(frozen=True)
class TickInput:
    now: float


@dataclass(frozen=True)
class TickResponse:
    swept: List[str]
    pruned: int
    spawned: List[str]


class TickUseCase:

    def __init__(self, store, workers, spawner, config):
        self._store = store
        self._workers = workers
        self._spawner = spawner
        self._config = config
        self._sweep = SweepUseCase(store, workers)

    def execute(self, input: TickInput) -> TickResponse:
        swept = self._sweep.execute()
        spawned = []
        pool = WorkerPool.from_state(self._workers.workers_state())
        probe = self._workers.pid_alive
        slots = pool.free_slots(self._config.max_agents(), probe)
        if slots > 0:
            inflight = pool.inflight(probe, input.now, self._config.max_boot_seconds())
            roles = ReadyQueue(self._store.ready_tasks()).roles()
            for role in PoolPlan(inflight, slots).roles_to_spawn(roles):
                self._spawner.spawn_worker(role)
                spawned.append(role)
        return TickResponse(swept=swept.swept, pruned=swept.pruned, spawned=spawned)

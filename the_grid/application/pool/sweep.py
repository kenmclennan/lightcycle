"""Sweep: reclaim orphaned task claims and prune dead worker entries.

A task is owned by a live worker iff its assignee is the spawnid of a worker
whose pid is alive. The spawnid->pid mapping is written at spawn (before the
claim), so it never lags - a just-claimed task is protected immediately.
"""
from dataclasses import dataclass
from typing import List

from the_grid.domain.pool import WorkerPool


@dataclass(frozen=True)
class SweepResponse:
    swept: List[str]
    pruned: int


class SweepUseCase:

    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def execute(self) -> SweepResponse:
        live = WorkerPool.from_state(self._workers.workers_state()).live_spawnids(
            self._workers.pid_alive)
        swept = []
        for t in self._store.claimed_tasks():
            if t.claimed_by in live:
                continue
            self._store.reclaim(t.id)
            swept.append(t.id)
        return SweepResponse(swept=swept, pruned=self._workers.prune_workers())

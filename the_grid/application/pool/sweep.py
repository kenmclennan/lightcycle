from dataclasses import dataclass
from typing import List

from the_grid.domain.pool import WorkerPool


@dataclass(frozen=True)
class SweepResponse:
    swept: List[str]
    killed: List[str]
    pruned: int


class SweepUseCase:
    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def execute(self, now, max_boot) -> SweepResponse:
        probe = self._workers.pid_alive
        pool = WorkerPool.from_state(self._workers.workers_state())
        live = pool.live_spawnids(probe)
        claimed = self._store.claimed_tasks()
        swept = []
        for t in claimed:
            if t.claimed_by in live:
                continue
            self._store.reclaim(t.id)
            swept.append(t.id)
        claimed_spawnids = {t.claimed_by for t in claimed}
        orphaned = pool.orphaned(probe, now, max_boot, claimed_spawnids)
        for w in orphaned:
            self._workers.kill(w.pid)
        return SweepResponse(
            swept=swept,
            killed=[w.spawnid for w in orphaned],
            pruned=self._workers.prune_workers(),
        )

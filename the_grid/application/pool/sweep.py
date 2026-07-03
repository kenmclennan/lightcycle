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
            self._workers.pid_alive
        )
        swept = []
        for t in self._store.claimed_tasks():
            if t.claimed_by in live:
                continue
            self._store.reclaim(t.id)
            swept.append(t.id)
        return SweepResponse(swept=swept, pruned=self._workers.prune_workers())

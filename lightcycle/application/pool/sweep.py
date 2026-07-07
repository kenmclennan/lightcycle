from dataclasses import dataclass
from typing import List

from lightcycle.domain.pool import WorkerPool


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
        claimed = self._store.claimed_steps()
        claimed_ids = {t.id for t in claimed}
        covered = pool.covered_steps(probe)
        booting = pool.any_booting(probe, now, max_boot)
        swept = []
        for t in claimed:
            if t.id in covered or booting:
                continue
            self._store.reclaim(t.id)
            swept.append(t.id)
        orphans = pool.orphans(probe, now, max_boot, claimed_ids)
        for w in orphans:
            self._workers.kill(w.pid)
        return SweepResponse(
            swept=swept,
            killed=[w.spawnid for w in orphans],
            pruned=self._workers.prune_workers(),
        )

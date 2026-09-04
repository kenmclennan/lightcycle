from dataclasses import dataclass, field
from typing import List

from lightcycle.domain.pool import WorkerPool


@dataclass(frozen=True)
class StopPoolResponse:
    stopped: List[str] = field(default_factory=list)
    reclaimed: List[str] = field(default_factory=list)
    preserved: List[str] = field(default_factory=list)
    capture_failed: List[str] = field(default_factory=list)


class StopPoolUseCase:
    def __init__(self, workers, sweep):
        self._workers = workers
        self._sweep = sweep

    def execute(self, now, max_boot, stall_seconds) -> StopPoolResponse:
        pool = WorkerPool.from_state(self._workers.workers_state())
        alive = pool.alive(self._workers.pid_alive)
        for worker in alive:
            self._workers.kill(worker.pid)
        swept = self._sweep.execute(now, max_boot, stall_seconds)
        return StopPoolResponse(
            stopped=[w.spawnid for w in alive],
            reclaimed=list(swept.swept),
            preserved=list(swept.preserved),
            capture_failed=list(swept.capture_failed),
        )

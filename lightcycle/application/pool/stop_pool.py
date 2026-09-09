import time
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
    def __init__(self, workers, sweep, sleep=time.sleep, clock=time.time):
        self._workers = workers
        self._sweep = sweep
        self._sleep = sleep
        self._clock = clock

    def execute(self, now, max_boot, stall_seconds, shutdown_grace_seconds=0) -> StopPoolResponse:
        pool = WorkerPool.from_state(self._workers.workers_state())
        alive = pool.alive(self._workers.pid_alive)
        for worker in alive:
            self._workers.kill(worker.pid)
        self._wait_for_death({w.pid for w in alive}, shutdown_grace_seconds)
        swept = self._sweep.execute(now, max_boot, stall_seconds)
        return StopPoolResponse(
            stopped=[w.spawnid for w in alive],
            reclaimed=list(swept.swept),
            preserved=list(swept.preserved),
            capture_failed=list(swept.capture_failed),
        )

    def _wait_for_death(self, pending, shutdown_grace_seconds):
        deadline = self._clock() + shutdown_grace_seconds
        while pending:
            self._workers.reap()
            pending = {pid for pid in pending if self._workers.pid_alive(pid)}
            if not pending or self._clock() >= deadline:
                return
            self._sleep(0.05)

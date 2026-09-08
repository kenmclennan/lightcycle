from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import WorkerPool


@dataclass(frozen=True)
class StartPoolResponse:
    started: bool
    pid: Optional[int] = None


@dataclass(frozen=True)
class StopPoolSignalResponse:
    signalled: bool
    pid: Optional[int] = None


class StartPoolUseCase:
    def __init__(self, lock, spawner):
        self._lock = lock
        self._spawner = spawner

    def execute(self) -> StartPoolResponse:
        pid = self._lock.holder_pid()
        if pid is not None:
            return StartPoolResponse(started=False, pid=pid)
        return StartPoolResponse(started=True, pid=self._spawner.spawn_pool())


class StopPoolSignalUseCase:
    def __init__(self, lock, workers):
        self._lock = lock
        self._workers = workers

    def execute(self) -> StopPoolSignalResponse:
        pid = self._lock.holder_pid()
        if pid is None:
            return StopPoolSignalResponse(signalled=False)
        self._workers.kill(pid)
        return StopPoolSignalResponse(signalled=True, pid=pid)


class LiveWorkerCountUseCase:
    def __init__(self, workers):
        self._workers = workers

    def execute(self) -> int:
        pool = WorkerPool.from_state(self._workers.workers_state())
        return len(pool.alive(self._workers.pid_alive))

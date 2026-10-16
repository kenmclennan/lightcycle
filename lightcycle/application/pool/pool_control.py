from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import WorkerPool
from lightcycle.domain.work import State, is_engine_step
from lightcycle.ports.workers import RegistryUnreadable


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
        pool = WorkerPool(self._workers.workers_state())
        return len(pool.alive(self._workers.pid_alive))


@dataclass(frozen=True)
class DrainPoolResponse:
    outcome: str
    pid: Optional[int] = None


DRAIN_SLOW_SECONDS = 1800


def _plural(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


@dataclass(frozen=True)
class PoolDrainStatus:
    draining: bool
    running: int
    engine_steps: int = 0
    slow: bool = False

    def waiting_text(self):
        parts = [_plural(self.running, "worker")]
        if self.engine_steps:
            parts.append(_plural(self.engine_steps, "engine step"))
        text = ", ".join(parts)
        return text + " - slow" if self.slow else text


class DrainPoolUseCase:
    def __init__(self, lock, drain):
        self._lock = lock
        self._drain = drain

    def execute(self) -> DrainPoolResponse:
        pid = self._lock.holder_pid()
        if pid is None:
            return DrainPoolResponse(outcome="no-pool")
        if self._drain.requested():
            return DrainPoolResponse(outcome="already-draining", pid=pid)
        self._drain.request()
        return DrainPoolResponse(outcome="requested", pid=pid)


class PoolDrainStatusUseCase:
    def __init__(self, drain, workers, store):
        self._drain = drain
        self._workers = workers
        self._store = store

    def execute(self, pool_running, now) -> PoolDrainStatus:
        if not (pool_running and self._drain.requested()):
            return PoolDrainStatus(draining=False, running=0)
        try:
            pool = WorkerPool(self._workers.workers_state())
            running = len(pool.alive(self._workers.pid_alive))
        except RegistryUnreadable:
            running = 0
        engine_steps = sum(
            1 for step in self._store.all_steps()
            if is_engine_step(step) and step.state in (State.QUEUED, State.RUNNING)
        )
        since = self._drain.requested_at()
        slow = since is not None and now - since > DRAIN_SLOW_SECONDS
        return PoolDrainStatus(
            draining=True, running=running, engine_steps=engine_steps, slow=slow
        )


class ClearDrainUseCase:
    def __init__(self, drain):
        self._drain = drain

    def execute(self):
        self._drain.clear()

from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import admission_cap, worker_to_resume, worker_to_suspend


@dataclass(frozen=True)
class MemoryGateResponse:
    cap: Optional[int]
    pressure: Optional[float]
    suspended: Optional[str] = None
    resumed: Optional[str] = None


class MemoryGateUseCase:
    def __init__(self, machine, workers, worker_log, config):
        self._machine = machine
        self._workers = workers
        self._worker_log = worker_log
        self._config = config

    def execute(self, pool, probe, now) -> MemoryGateResponse:
        alive = pool.alive(probe)
        headroom = self._machine.headroom(alive)
        pressure = headroom.system_pressure if headroom else None
        cap = admission_cap(headroom, len(alive), self._config.memory_reserve_fraction())

        suspended = None
        target = worker_to_suspend(alive, pressure, self._config.suspend_pressure())
        if target is not None:
            self._workers.signal_suspend(target.pid)
            self._workers.set_suspended(target.spawnid, True, now)
            suspended = target.spawnid

        resumed = None
        resume_target = worker_to_resume(alive, pressure, self._config.resume_pressure())
        if resume_target is not None:
            self._workers.signal_resume(resume_target.pid)
            self._workers.set_suspended(resume_target.spawnid, False)
            self._worker_log.touch(resume_target.log)
            resumed = resume_target.spawnid

        return MemoryGateResponse(cap=cap, pressure=pressure, suspended=suspended, resumed=resumed)

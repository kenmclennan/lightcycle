from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import (
    admission_cap, admission_veto, worker_to_resume, worker_to_suspend,
)


@dataclass(frozen=True)
class MemoryGateResponse:
    cap: Optional[int]
    pool_share: Optional[float]
    peak_worker_share: Optional[float] = None
    suspended: Optional[str] = None
    resumed: Optional[str] = None


class MemoryGateUseCase:
    def __init__(self, machine, workers, worker_log, config, memory_gate_status):
        self._machine = machine
        self._workers = workers
        self._worker_log = worker_log
        self._config = config
        self._memory_gate_status = memory_gate_status

    def execute(self, pool, probe, now) -> MemoryGateResponse:
        alive = pool.alive(probe)
        headroom = self._machine.headroom(alive)
        pool_share = headroom.pool_share if headroom else None
        peak_worker_share = headroom.peak_worker_share if headroom else None
        working = sum(1 for w in alive if not w.suspended)
        cap = admission_cap(headroom, working, self._config.memory_reserve_fraction())
        veto = admission_veto(pool_share, self._config.suspend_pressure(), working)
        vetoed_caps = [c for c in (cap, veto) if c is not None]
        vetoed_cap = min(vetoed_caps) if vetoed_caps else None

        suspended = None
        target = worker_to_suspend(alive, pool_share, self._config.suspend_pressure())
        if target is not None:
            self._workers.signal_suspend(target.pid)
            self._workers.set_suspended(target.spawnid, True, now)
            suspended = target.spawnid

        resumed = None
        resume_target = worker_to_resume(alive, pool_share, self._config.resume_pressure())
        if resume_target is not None:
            self._workers.signal_resume(resume_target.pid)
            self._workers.set_suspended(resume_target.spawnid, False)
            self._worker_log.touch(resume_target.log)
            resumed = resume_target.spawnid

        self._memory_gate_status.save(
            {"cap": vetoed_cap, "pool_share": pool_share,
             "peak_worker_share": peak_worker_share}
        )
        return MemoryGateResponse(
            cap=vetoed_cap, pool_share=pool_share,
            peak_worker_share=peak_worker_share, suspended=suspended, resumed=resumed,
        )

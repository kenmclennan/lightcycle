from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import admission_cap, worker_to_resume


@dataclass(frozen=True)
class MemoryGateResponse:
    cap: Optional[int]
    pool_share: Optional[float]
    peak_worker_share: Optional[float] = None
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

        resumed = None
        resume_target = worker_to_resume(alive)
        if resume_target is not None:
            self._workers.signal_resume(resume_target.pid)
            self._workers.set_suspended(resume_target.spawnid, False)
            self._worker_log.touch(resume_target.log)
            resumed = resume_target.spawnid

        self._memory_gate_status.save(
            {"cap": cap, "pool_share": pool_share,
             "peak_worker_share": peak_worker_share}
        )
        return MemoryGateResponse(
            cap=cap, pool_share=pool_share,
            peak_worker_share=peak_worker_share, resumed=resumed,
        )

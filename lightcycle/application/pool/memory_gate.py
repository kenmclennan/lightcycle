from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import admission_cap


@dataclass(frozen=True)
class MemoryGateResponse:
    cap: Optional[int]
    pool_share: Optional[float]
    peak_worker_share: Optional[float] = None


class MemoryGateUseCase:
    def __init__(self, machine, config, memory_gate_status):
        self._machine = machine
        self._config = config
        self._memory_gate_status = memory_gate_status

    def execute(self, pool, probe, now) -> MemoryGateResponse:
        alive = pool.alive(probe)
        headroom = self._machine.headroom(alive)
        pool_share = headroom.pool_share if headroom else None
        peak_worker_share = headroom.peak_worker_share if headroom else None
        cap = admission_cap(headroom, len(alive), self._config.memory_reserve_fraction())

        self._memory_gate_status.save(
            {"cap": cap, "pool_share": pool_share,
             "peak_worker_share": peak_worker_share}
        )
        return MemoryGateResponse(
            cap=cap, pool_share=pool_share,
            peak_worker_share=peak_worker_share,
        )

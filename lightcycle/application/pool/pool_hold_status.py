from dataclasses import dataclass

from lightcycle.domain.pool import WorkerPool
from lightcycle.ports.workers import RegistryUnreadable


@dataclass(frozen=True)
class PoolHoldResponse:
    holding: bool
    alive: int
    max_agents: int
    reason: str = "memory"


class PoolHoldStatusUseCase:
    def __init__(self, memory_gate_status, workers, config):
        self._memory_gate_status = memory_gate_status
        self._workers = workers
        self._config = config

    def execute(self, probe) -> PoolHoldResponse:
        max_agents = self._config.max_agents()
        try:
            pool = WorkerPool(self._workers.workers_state())
        except RegistryUnreadable:
            return PoolHoldResponse(holding=False, alive=0, max_agents=max_agents)
        alive = pool.alive(probe)
        state = self._memory_gate_status.load()
        cap = state.get("cap")
        suspended = any(w.suspended for w in alive)
        return PoolHoldResponse(
            holding=cap == 0 or suspended, alive=len(alive), max_agents=max_agents,
        )

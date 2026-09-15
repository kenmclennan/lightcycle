from dataclasses import dataclass

from lightcycle.domain.pool import WorkerPool, admission_cap
from lightcycle.ports.workers import RegistryUnreadable


@dataclass(frozen=True)
class PoolHoldResponse:
    holding: bool
    alive: int
    max_agents: int
    reason: str = "memory"


class PoolHoldStatusUseCase:
    def __init__(self, machine, workers, config):
        self._machine = machine
        self._workers = workers
        self._config = config

    def execute(self, probe) -> PoolHoldResponse:
        max_agents = self._config.max_agents()
        try:
            pool = WorkerPool(self._workers.workers_state())
        except RegistryUnreadable:
            return PoolHoldResponse(holding=False, alive=0, max_agents=max_agents)
        alive = pool.alive(probe)
        headroom = self._machine.headroom(alive)
        cap = admission_cap(headroom, len(alive), self._config.memory_reserve_fraction())
        holding = cap == 0 and len(alive) < max_agents
        return PoolHoldResponse(holding=holding, alive=len(alive), max_agents=max_agents)

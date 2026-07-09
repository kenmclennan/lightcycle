from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from lightcycle.application.pool.sweep import SweepUseCase
from lightcycle.domain.pool import Breaker, PoolPlan, ReadyQueue, WorkerPool


@dataclass(frozen=True)
class TickInput:
    now: float
    since: Optional[float] = None


@dataclass(frozen=True)
class TickResponse:
    swept: List[str]
    pruned: int
    spawned: List[str]
    merged: List[str] = field(default_factory=list)
    abandoned: List[str] = field(default_factory=list)
    reworked: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)
    cadence_fired: List[str] = field(default_factory=list)
    hook_completed: List[Tuple[str, str, str]] = field(default_factory=list)
    alive: int = 0
    max_agents: int = 0
    ready: int = 0
    inflight_count: int = 0
    breaker_open: bool = False
    breaker_reset_at: Optional[float] = None
    breaker_opened: bool = False
    breaker_closed: bool = False


class TickUseCase:
    def __init__(
        self, store, workers, spawner, config, monitor=None, cadence_gate=None, breaker_gate=None,
        hook_completions=None,
    ):
        self._store = store
        self._workers = workers
        self._spawner = spawner
        self._config = config
        self._sweep = SweepUseCase(store, workers)
        self._monitor = monitor
        self._cadence_gate = cadence_gate
        self._breaker_gate = breaker_gate
        self._hook_completions = hook_completions

    def execute(self, input: TickInput) -> TickResponse:
        self._workers.reap()
        monitor_result = self._monitor.execute() if self._monitor else None
        merged = monitor_result.merged if monitor_result else []
        abandoned = monitor_result.abandoned if monitor_result else []
        reworked = monitor_result.reworked if monitor_result else []
        conflicted = monitor_result.conflicted if monitor_result else []
        cadence_result = self._cadence_gate.execute(input.now) if self._cadence_gate else None
        cadence_fired = cadence_result.fired if cadence_result else []
        hook_result = self._hook_completions.execute(input.since) if self._hook_completions else None
        hook_completed = hook_result.completed if hook_result else []
        breaker_result = self._breaker_gate.execute(input.now) if self._breaker_gate else None
        breaker = breaker_result.breaker if breaker_result else Breaker()
        swept = self._sweep.execute(input.now, self._config.max_boot_seconds())
        pool = WorkerPool.from_state(self._workers.workers_state())
        probe = self._workers.pid_alive
        max_agents = self._config.max_agents()
        slots = pool.free_slots(max_agents, probe)
        alive_count = max_agents - slots
        cap = breaker.spawn_cap(input.now, alive_count)
        if cap is not None:
            slots = min(slots, cap)
        inflight_dict = pool.inflight(probe, input.now, self._config.max_boot_seconds())
        inflight_total = sum(inflight_dict.values())
        ready_roles = ReadyQueue(self._store.ready_steps()).roles()
        ready_count = len(ready_roles)
        spawned = []
        if slots > 0:
            for role in PoolPlan(inflight_dict, slots).roles_to_spawn(ready_roles):
                self._spawner.spawn_worker(role)
                spawned.append(role)
        return TickResponse(
            swept=swept.swept,
            pruned=swept.pruned,
            spawned=spawned,
            merged=merged,
            abandoned=abandoned,
            reworked=reworked,
            conflicted=conflicted,
            cadence_fired=cadence_fired,
            hook_completed=hook_completed,
            alive=alive_count,
            max_agents=max_agents,
            ready=ready_count,
            inflight_count=inflight_total,
            breaker_open=breaker.is_open,
            breaker_reset_at=breaker.reset_at,
            breaker_opened=breaker_result.opened if breaker_result else False,
            breaker_closed=breaker_result.closed if breaker_result else False,
        )

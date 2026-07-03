"""Tick: one pass of the agent pool - sweep, then fill workers from the queue.

Fill up to GRID_MAX_AGENTS alive workers from the ready queue, one worker per
uncovered ready task regardless of role (bd ready already hides blocked-by tasks,
so declared dependencies are honoured for free). A worker that has spawned but
not yet claimed (task is None) within the boot window covers a task of its role,
so the pool does not pile redundant workers onto one task. `now` is passed in
(the caller owns the clock).
"""
from dataclasses import dataclass, field
from typing import List

from the_grid.application.pool.sweep import SweepUseCase
from the_grid.domain.pool import PoolPlan, ReadyQueue, WorkerPool


@dataclass(frozen=True)
class TickInput:
    now: float


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
    alive: int = 0
    max_agents: int = 0
    ready: int = 0
    inflight_count: int = 0


class TickUseCase:

    def __init__(self, store, workers, spawner, config, monitor=None, cadence_gate=None):
        self._store = store
        self._workers = workers
        self._spawner = spawner
        self._config = config
        self._sweep = SweepUseCase(store, workers)
        self._monitor = monitor
        self._cadence_gate = cadence_gate

    def execute(self, input: TickInput) -> TickResponse:
        monitor_result = self._monitor.execute() if self._monitor else None
        merged = monitor_result.merged if monitor_result else []
        abandoned = monitor_result.abandoned if monitor_result else []
        reworked = monitor_result.reworked if monitor_result else []
        conflicted = monitor_result.conflicted if monitor_result else []
        cadence_result = self._cadence_gate.execute(input.now) if self._cadence_gate else None
        cadence_fired = cadence_result.fired if cadence_result else []
        swept = self._sweep.execute()
        pool = WorkerPool.from_state(self._workers.workers_state())
        probe = self._workers.pid_alive
        max_agents = self._config.max_agents()
        slots = pool.free_slots(max_agents, probe)
        alive_count = max_agents - slots
        inflight_dict = pool.inflight(probe, input.now, self._config.max_boot_seconds())
        inflight_total = sum(inflight_dict.values())
        ready_roles = ReadyQueue(self._store.ready_tasks()).roles()
        ready_count = len(ready_roles)
        spawned = []
        if slots > 0:
            for role in PoolPlan(inflight_dict, slots).roles_to_spawn(ready_roles):
                self._spawner.spawn_worker(role)
                spawned.append(role)
        return TickResponse(
            swept=swept.swept, pruned=swept.pruned, spawned=spawned, merged=merged,
            abandoned=abandoned, reworked=reworked, conflicted=conflicted,
            cadence_fired=cadence_fired,
            alive=alive_count, max_agents=max_agents, ready=ready_count,
            inflight_count=inflight_total,
        )

from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.pool.backup import BackupResponse
from lightcycle.application.pool.hook_completions import HookCompletionsResponse
from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.retro_cadence import RetroCadenceResponse
from lightcycle.application.pool.sweep import SweepResponse, SweepUseCase
from lightcycle.domain.pool import PoolPlan, ReadyQueue, WorkerPool
from lightcycle.ports.workers import RegistryUnreadable

_ACTIVE_ACCRUAL_CAP_TICKS = 3


@dataclass(frozen=True)
class TickInput:
    now: float
    since: Optional[float] = None


@dataclass(frozen=True)
class PoolState:
    alive: int
    max_agents: int
    ready: int
    inflight_count: int
    free_slots: int


@dataclass(frozen=True)
class BreakerState:
    open: bool
    reset_at: Optional[float]
    opened: bool
    closed: bool
    rearmed: bool
    spin_open: bool
    spin_opened: bool


@dataclass(frozen=True)
class TickResponse:
    sweep: SweepResponse
    spawned: List[str]
    monitor: MonitorPrsResponse
    cadence: RetroCadenceResponse
    hooks: HookCompletionsResponse
    backup: BackupResponse
    pool: PoolState
    breaker: BreakerState


class TickUseCase:
    def __init__(
        self, store, workers, spawner, config, monitor, cadence_gate, breaker_gate,
        hook_completions, worktrees, git, backup_gate, fs, flow_service, spin_port, usage_gate,
        stream,
    ):
        self._store = store
        self._workers = workers
        self._spawner = spawner
        self._config = config
        self._sweep = SweepUseCase(
            store, workers, worktrees, git, fs,
            spin_port=spin_port, spin_cap=config.spin_cap(), stream=stream,
        )
        self._monitor = monitor
        self._cadence_gate = cadence_gate
        self._breaker_gate = breaker_gate
        self._hook_completions = hook_completions
        self._backup_gate = backup_gate
        self._flow_service = flow_service
        self._usage_gate = usage_gate

    def execute(self, input: TickInput) -> TickResponse:
        self._flow_service.clear_cache()
        self._workers.reap()
        monitor_result = self._monitor.execute()
        cadence_result = self._cadence_gate.execute(input.now)
        breaker_result = self._breaker_gate.execute(input.now)
        breaker = breaker_result.breaker
        backup_result = self._backup_gate.execute(input.now)
        self._usage_gate.execute(input.now)
        swept = self._sweep.execute(
            input.now, self._config.max_boot_seconds(), self._config.stall_seconds()
        )
        probe = self._workers.pid_alive
        max_agents = self._config.max_agents()
        try:
            pool = WorkerPool(self._workers.workers_state())
            covered = pool.covered_steps(probe)
            slots = pool.free_slots(max_agents, probe)
            alive_count = max_agents - slots
            inflight_dict = pool.inflight(probe, input.now, self._config.max_boot_seconds())
        except RegistryUnreadable:
            covered = set()
            slots = 0
            alive_count = max_agents
            inflight_dict = {}
        cap = breaker.spawn_cap(input.now, alive_count)
        if cap is not None:
            slots = min(slots, cap)
        if breaker_result.spin_open:
            slots = min(slots, 1)
        inflight_total = sum(inflight_dict.values())
        ready_roles = ReadyQueue(self._store.ready_steps()).roles()
        ready_count = len(ready_roles)
        spawned = []
        if slots > 0:
            for role in PoolPlan(inflight_dict, slots).roles_to_spawn(ready_roles):
                self._spawner.spawn_worker(role)
                spawned.append(role)
        hook_result = self._hook_completions.execute(input.since)
        if covered and input.since is not None:
            delta = min(
                input.now - input.since, self._config.poll_seconds() * _ACTIVE_ACCRUAL_CAP_TICKS
            )
            if delta > 0:
                self._store.accrue_active_seconds(covered, delta)
        return TickResponse(
            sweep=swept,
            spawned=spawned,
            monitor=monitor_result,
            cadence=cadence_result,
            hooks=hook_result,
            backup=backup_result,
            pool=PoolState(
                alive=alive_count,
                max_agents=max_agents,
                ready=ready_count,
                inflight_count=inflight_total,
                free_slots=slots,
            ),
            breaker=BreakerState(
                open=breaker.is_open,
                reset_at=breaker.reset_at,
                opened=breaker_result.opened,
                closed=breaker_result.closed,
                rearmed=breaker_result.rearmed,
                spin_open=breaker_result.spin_open,
                spin_opened=breaker_result.spin_opened,
            ),
        )

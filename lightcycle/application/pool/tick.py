import sys
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.pool.backup import BackupResponse
from lightcycle.application.pool.daily_summary_cadence import DailySummaryCadenceResponse
from lightcycle.application.pool.guidance_sync import GuidanceSyncResponse
from lightcycle.application.pool.hook_completions import HookCompletionsResponse
from lightcycle.application.pool.memory_gate import MemoryGateResponse
from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.material_audit_cadence import MaterialAuditCadenceResponse
from lightcycle.application.pool.reload_config import ReloadConfigResponse
from lightcycle.application.pool.retro_cadence import RetroCadenceResponse
from lightcycle.application.pool.schedule_cadence import ScheduleCadenceResponse
from lightcycle.application.pool.sweep import SweepResponse, SweepUseCase
from lightcycle.config import RELOAD_RELOADED, RELOAD_REJECTED
from lightcycle.domain.pool import PoolPlan, ReadyQueue, WorkerPool
from lightcycle.ports.git import GitReadError
from lightcycle.ports.workers import RegistryUnreadable

_ACTIVE_ACCRUAL_CAP_TICKS = 3


@dataclass(frozen=True)
class TickInput:
    now: float
    since: Optional[float] = None
    drain: bool = False


@dataclass(frozen=True)
class PoolState:
    alive: int
    max_agents: int
    ready: int
    inflight_count: int
    free_slots: int
    draining: bool = False


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
    summary: DailySummaryCadenceResponse
    hooks: HookCompletionsResponse
    backup: BackupResponse
    pool: PoolState
    breaker: BreakerState
    memory: Optional[MemoryGateResponse] = None
    guidance: Optional[GuidanceSyncResponse] = None
    material_audit: Optional[MaterialAuditCadenceResponse] = None
    schedules: Optional[ScheduleCadenceResponse] = None
    config: Optional[ReloadConfigResponse] = None


class TickUseCase:
    def __init__(
        self, store, workers, spawner, config, monitor, cadence_gate, breaker_gate,
        hook_completions, worktrees, git, backup_gate, fs, flow_service, spin_port, usage_gate,
        stream, memory_gate, summary_gate, guidance_gate,
        material_audit_gate, schedule_gate, config_reload,
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
        self._summary_gate = summary_gate
        self._material_audit_gate = material_audit_gate
        self._schedule_gate = schedule_gate
        self._config_reload = config_reload
        self._breaker_gate = breaker_gate
        self._hook_completions = hook_completions
        self._backup_gate = backup_gate
        self._flow_service = flow_service
        self._usage_gate = usage_gate
        self._memory_gate = memory_gate
        self._guidance_gate = guidance_gate

    def _guidance_sync(self, now):
        try:
            return self._guidance_gate.execute(now)
        except (OSError, GitReadError) as e:
            sys.stderr.write("warning: guidance sync failed: %s\n" % e)
            return None

    def _schedules(self, now):
        try:
            return self._schedule_gate.execute(now)
        except (OSError, GitReadError, ValueError) as e:
            sys.stderr.write("warning: schedule check failed: %s\n" % e)
            return None

    def _reload_config(self):
        result = self._config_reload.execute()
        if result.outcome == RELOAD_RELOADED:
            self._schedule_gate.reset()
        elif result.outcome == RELOAD_REJECTED:
            sys.stderr.write(
                "warning: config reload rejected: %s - keeping the last good config\n"
                % result.reason)
        return result

    def execute(self, input: TickInput) -> TickResponse:
        config_result = self._reload_config()
        self._flow_service.clear_cache()
        self._workers.reap()
        monitor_result = self._monitor.execute()
        cadence_result = self._cadence_gate.execute(input.now)
        summary_result = self._summary_gate.execute(input.now)
        material_audit_result = self._material_audit_gate.execute(input.now)
        schedules_result = self._schedules(input.now)
        breaker_result = self._breaker_gate.execute(input.now)
        breaker = breaker_result.breaker
        backup_result = self._backup_gate.execute(input.now)
        guidance_result = self._guidance_sync(input.now)
        self._usage_gate.execute(input.now)
        swept = self._sweep.execute(
            input.now, self._config.max_boot_seconds(), self._config.stall_seconds()
        )
        probe = self._workers.pid_alive
        max_agents = self._config.max_agents()
        try:
            pool = WorkerPool(self._workers.workers_state())
            running = pool.covered_steps(probe)
            slots = pool.free_slots(max_agents, probe)
            alive_count = max_agents - slots
            inflight_dict = pool.inflight(probe, input.now, self._config.max_boot_seconds())
            memory_result = self._memory_gate.execute(pool, probe)
        except RegistryUnreadable:
            running = set()
            slots = 0
            alive_count = max_agents
            inflight_dict = {}
            memory_result = None
        cap = breaker.spawn_cap(input.now, alive_count)
        if cap is not None:
            slots = min(slots, cap)
        if memory_result is not None and memory_result.cap is not None:
            slots = min(slots, memory_result.cap)
        if breaker_result.spin_open:
            slots = min(slots, 1)
        if input.drain:
            slots = 0
        inflight_total = sum(inflight_dict.values())
        ready_roles = ReadyQueue(self._store.ready_steps()).roles()
        ready_count = len(ready_roles)
        spawned = []
        if slots > 0:
            for role in PoolPlan(inflight_dict, slots).roles_to_spawn(ready_roles):
                self._spawner.spawn_worker(role)
                spawned.append(role)
        hook_result = self._hook_completions.execute(input.since)
        if running and input.since is not None:
            delta = min(
                input.now - input.since, self._config.poll_seconds() * _ACTIVE_ACCRUAL_CAP_TICKS
            )
            if delta > 0:
                self._store.accrue_active_seconds(running, delta)
        return TickResponse(
            sweep=swept,
            spawned=spawned,
            monitor=monitor_result,
            cadence=cadence_result,
            summary=summary_result,
            hooks=hook_result,
            backup=backup_result,
            pool=PoolState(
                alive=alive_count,
                max_agents=max_agents,
                ready=ready_count,
                inflight_count=inflight_total,
                free_slots=slots,
                draining=input.drain,
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
            memory=memory_result,
            guidance=guidance_result,
            material_audit=material_audit_result,
            schedules=schedules_result,
            config=config_result,
        )

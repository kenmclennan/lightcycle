import sys
import time
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.pool.backup import BackupResponse
from lightcycle.application.pool.close_stranded_items import CloseStrandedItemsResponse
from lightcycle.application.pool.github_budget import GithubBudgetState
from lightcycle.application.pool.guidance_sync import GuidanceSyncResponse
from lightcycle.application.pool.hook_completions import HookCompletionsResponse
from lightcycle.application.pool.lifecycle_cadence import LifecycleCadenceResponse
from lightcycle.application.pool.memory_gate import MemoryGateResponse
from lightcycle.application.pool.monitor_prs import MonitorPrsResponse
from lightcycle.application.pool.release_interrupted_runs import ReleaseInterruptedRunsResponse
from lightcycle.application.pool.reload_config import ReloadConfigResponse
from lightcycle.application.pool.schedule_cadence import ScheduleCadenceResponse
from lightcycle.application.pool.script_stages import ScriptStagesResponse
from lightcycle.application.pool.sweep import SweepResponse
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
    hooks: HookCompletionsResponse
    backup: BackupResponse
    pool: PoolState
    breaker: BreakerState
    memory: Optional[MemoryGateResponse] = None
    guidance: Optional[GuidanceSyncResponse] = None
    schedules: Optional[ScheduleCadenceResponse] = None
    lifecycle: Optional[LifecycleCadenceResponse] = None
    scripts: Optional[ScriptStagesResponse] = None
    config: Optional[ReloadConfigResponse] = None
    github: Optional[GithubBudgetState] = None
    released: Optional[ReleaseInterruptedRunsResponse] = None
    stranded: Optional[CloseStrandedItemsResponse] = None


class TickUseCase:
    def __init__(
        self, store, workers, spawner, config, monitor, breaker_gate,
        hook_completions, backup_gate, flow_service, memory_gate, guidance_gate,
        github_poll_gate, github_budget, config_reload, sweep, cadence, accrual, worker_log,
        release_gate, stranded_gate,
    ):
        self._store = store
        self._workers = workers
        self._spawner = spawner
        self._config = config
        self._sweep = sweep
        self._monitor = monitor
        self._worker_log = worker_log
        self._logged_refusals = {}
        self._github_poll_gate = github_poll_gate
        self._cadence = cadence
        self._accrual = accrual
        self._config_reload = config_reload
        self._breaker_gate = breaker_gate
        self._hook_completions = hook_completions
        self._backup_gate = backup_gate
        self._flow_service = flow_service
        self._memory_gate = memory_gate
        self._guidance_gate = guidance_gate
        self._github_budget = github_budget
        self._release_gate = release_gate
        self._stranded_gate = stranded_gate
        self._budget_low = False

    def _log_refusals(self, refused, now):
        current = dict(refused)
        for item, message in current.items():
            if self._logged_refusals.get(item) == message:
                continue
            self._worker_log.append_run_log("%s  %-7s  %s\n" % (
                time.strftime("%H:%M:%S", time.localtime(now)), "refused", message))
        self._logged_refusals = current

    def _guidance_sync(self, now):
        try:
            return self._guidance_gate.execute(now)
        except (OSError, GitReadError) as e:
            sys.stderr.write("warning: guidance sync failed: %s\n" % e)
            return None

    def _release_interrupted(self):
        result = self._release_gate.execute()
        for run_id, message in result.failed:
            sys.stderr.write(
                "warning: interrupted-run release failed for %s: %s\n" % (run_id, message))
        return result

    def _reload_config(self):
        result = self._config_reload.execute()
        if result.outcome == RELOAD_RELOADED:
            self._cadence.reset()
        elif result.outcome == RELOAD_REJECTED:
            sys.stderr.write(
                "warning: config reload rejected: %s - keeping the last good config\n"
                % result.reason)
        return result

    def prime(self, now):
        self._monitor.execute()
        if self._github_poll_gate.execute(now):
            self._github_poll_gate.settle()

    def execute(self, input: TickInput) -> TickResponse:
        config_result = self._reload_config()
        self._flow_service.clear_cache()
        self._workers.reap()
        released_result = self._release_interrupted()
        stranded_result = self._stranded_gate.execute()
        monitor_result = self._monitor.execute()
        self._github_poll_gate.execute(input.now)
        cadence_result = self._cadence.execute(input.now)
        schedules_result = cadence_result.schedules
        lifecycle_result = cadence_result.lifecycle
        scripts_result = cadence_result.scripts
        self._log_refusals(
            monitor_result.refused + (scripts_result.refused if scripts_result else []),
            input.now)
        breaker_result = self._breaker_gate.execute(input.now)
        breaker = breaker_result.breaker
        backup_result = self._backup_gate.execute(input.now)
        guidance_result = self._guidance_sync(input.now)
        self._accrual.execute(input.now)
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
        ready_steps = self._store.ready_steps()
        reading = self._github_budget.reading()
        held = self._github_budget.held(ready_steps)
        github_state = GithubBudgetState(
            reading=reading, opened=reading.low and not self._budget_low,
            closed=self._budget_low and not reading.low)
        self._budget_low = reading.low
        ready_roles = ReadyQueue([s for s in ready_steps if s.id not in held]).roles()
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
            schedules=schedules_result,
            lifecycle=lifecycle_result,
            scripts=scripts_result,
            config=config_result,
            github=github_state,
            released=released_result,
            stranded=stranded_result,
        )

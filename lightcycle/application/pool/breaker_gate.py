from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.domain.pool import Breaker, WorkerPool, parse_rate_limit_event
from lightcycle.domain.pool.worker_session import saw_session_activity, saw_terminal_command


@dataclass(frozen=True)
class BreakerGateResponse:
    breaker: Breaker
    opened: bool = False
    closed: bool = False
    rearmed: bool = False
    killed: List[str] = field(default_factory=list)
    spin_open: bool = False
    spin_opened: bool = False


class BreakerGateUseCase:
    def __init__(self, workers, fs, breaker_port, config, spin_port=None, store=None):
        self._workers = workers
        self._fs = fs
        self._breaker_port = breaker_port
        self._config = config
        self._spin_port = spin_port
        self._store = store

    def _pool_wide_spin(self, rejected, dead_with_step, no_work_with_step, saw_real_activity, rep_step):
        state = self._spin_port.load()
        pool_state = dict(state.get("pool") or {})
        streak = pool_state.get("streak", 0)
        tripped = pool_state.get("tripped", False)
        if not rejected and dead_with_step >= 2 and no_work_with_step == dead_with_step:
            streak += 1
        elif saw_real_activity:
            streak = 0
            tripped = False
        spin_opened = False
        spin_cap = self._config.spin_cap()
        if not tripped and streak >= spin_cap:
            tripped = True
            spin_opened = True
            if self._store is not None and rep_step is not None:
                observation = (
                    "%d workers across the pool died within one check, none producing any "
                    "model activity - a pool-wide pattern, not specific to this step."
                    % no_work_with_step
                )
                decision = (
                    "Confirm the pool can actually reach the model (auth, network, or model "
                    "access) before continuing - this looks like an engine-level problem, not "
                    "one specific to this step."
                )
                ParkStepUseCase(self._store).execute(
                    ParkInput(step=rep_step, observation=observation, decision=decision)
                )
        pool_state["streak"] = streak
        pool_state["tripped"] = tripped
        state["pool"] = pool_state
        self._spin_port.save(state)
        return tripped, spin_opened

    def execute(self, now) -> BreakerGateResponse:
        state = Breaker.from_state(self._breaker_port.load())
        pool = WorkerPool.from_state(self._workers.workers_state())
        probe = self._workers.pid_alive
        was_probing = state.is_probing(now)

        rejected_reset_ats = []
        any_success = False
        dead_with_step = 0
        no_work_with_step = 0
        saw_real_activity_with_step = False
        rep_step = None
        for w in pool.dead_unchecked(probe):
            event = parse_rate_limit_event(self._fs.iter_lines(w.log))
            no_work = not saw_session_activity(self._fs.iter_lines(w.log))
            self._workers.mark_checked(w.spawnid)
            if event and event.is_rejected:
                rejected_reset_ats.append(event.reset_at)
            elif not no_work:
                any_success = True
            if w.step is not None:
                dead_with_step += 1
                if no_work:
                    no_work_with_step += 1
                    if rep_step is None:
                        rep_step = w.step
                else:
                    saw_real_activity_with_step = True

        opened = False
        closed = False
        rearmed = False
        killed = []
        if rejected_reset_ats:
            state = state.trip(max(rejected_reset_ats))
            opened = True
            for alive in pool.alive(probe):
                self._workers.kill(alive.pid)
                killed.append(alive.spawnid)
        elif was_probing and any_success:
            state = state.close()
            closed = True
        elif was_probing:
            stalled_probes = [
                w
                for w in pool.stalled(
                    probe,
                    now,
                    self._config.max_boot_seconds(),
                    self._config.stall_seconds(),
                    self._workers.log_mtime,
                )
                if not saw_terminal_command(self._fs.iter_lines(w.log))
            ]
            if stalled_probes:
                state = state.rearm(now + self._config.probe_cooldown_seconds())
                rearmed = True

        spin_open = False
        spin_opened = False
        if self._spin_port is not None:
            spin_open, spin_opened = self._pool_wide_spin(
                bool(rejected_reset_ats), dead_with_step, no_work_with_step,
                saw_real_activity_with_step, rep_step,
            )

        self._breaker_port.save(state.as_dict())
        return BreakerGateResponse(
            breaker=state, opened=opened, closed=closed, rearmed=rearmed, killed=killed,
            spin_open=spin_open, spin_opened=spin_opened,
        )

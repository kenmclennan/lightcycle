from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.domain.pool import (
    AttributionEvent, Breaker, ToolUsage, UsageEvent, WorkerPool, parse_attribution_event,
    parse_rate_limit_event, parse_usage_event, resolve_usage,
)
from lightcycle.domain.pool.worker_session import saw_session_activity
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.ports.workers import RegistryUnreadable


def _corrected_usage(usage, resume):
    posted_thinking = resume.get("posted_thinking_tokens")
    thinking_tokens = None
    if usage.thinking_tokens is not None:
        thinking_tokens = usage.thinking_tokens - (posted_thinking or 0)
    return UsageEvent(
        input_tokens=usage.input_tokens - (resume.get("posted_input_tokens", 0) or 0),
        output_tokens=usage.output_tokens - (resume.get("posted_output_tokens", 0) or 0),
        cache_read_tokens=(
            usage.cache_read_tokens - (resume.get("posted_cache_read_tokens", 0) or 0)
        ),
        cache_creation_tokens=(
            usage.cache_creation_tokens - (resume.get("posted_cache_creation_tokens", 0) or 0)
        ),
        cost_usd=usage.cost_usd - (resume.get("posted_cost_usd", 0.0) or 0.0),
        cost_basis=usage.cost_basis,
        thinking_tokens=thinking_tokens,
        has_result_line=usage.has_result_line,
    )


def _corrected_attribution(attribution, resume):
    posted_tool_usage = resume.get("posted_tool_usage") or {}
    tool_usage = {}
    for tool, usage in attribution.tool_usage.items():
        posted = posted_tool_usage.get(tool) or {}
        tool_usage[tool] = ToolUsage(
            calls=usage.calls - (posted.get("calls", 0) or 0),
            bytes=usage.bytes - (posted.get("bytes", 0) or 0),
        )
    return AttributionEvent(
        turn_count=attribution.turn_count - (resume.get("posted_turn_count", 0) or 0),
        tool_usage=tool_usage,
        recovered_input_tokens=attribution.recovered_input_tokens,
        recovered_output_tokens=attribution.recovered_output_tokens,
        recovered_cache_read_tokens=attribution.recovered_cache_read_tokens,
        recovered_cache_creation_tokens=attribution.recovered_cache_creation_tokens,
    )


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
        spin_cap = self._config.spin_cap()
        outcome = {}

        def _mutate(ledger):
            new_ledger, tripped, spin_opened = ledger.advance_pool(
                rejected, dead_with_step, no_work_with_step, saw_real_activity, spin_cap
            )
            outcome["tripped"] = tripped
            outcome["spin_opened"] = spin_opened
            return new_ledger

        self._spin_port.update(_mutate)
        if outcome["spin_opened"] and self._store is not None and rep_step is not None:
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
        return outcome["tripped"], outcome["spin_opened"]

    def _probe_signal(self, w, now):
        event = parse_rate_limit_event(self._fs.iter_lines(w.log))
        if event and event.is_rejected:
            return "rejected"
        if saw_session_activity(self._fs.iter_lines(w.log)):
            return "success"
        if w.is_stalled(
            now,
            self._config.max_boot_seconds(),
            self._config.stall_seconds(),
            self._workers.log_mtime,
        ):
            return "stalled"
        return None

    def execute(self, now) -> BreakerGateResponse:
        state = Breaker.from_state(self._breaker_port.load())
        try:
            pool = WorkerPool.from_state(self._workers.workers_state())
        except RegistryUnreadable:
            return BreakerGateResponse(breaker=state)
        probe = self._workers.pid_alive
        was_probing = state.is_probing(now)
        rates = self._config.usage_pricing()

        rejected_reset_ats = []
        any_success = False
        dead_with_step = 0
        no_work_with_step = 0
        saw_real_activity_with_step = False
        rep_step = None
        for w in pool.dead_unchecked(probe):
            event = parse_rate_limit_event(self._fs.iter_lines(w.log))
            no_work = not saw_session_activity(self._fs.iter_lines(w.log))
            if self._store is not None and w.step is not None:
                usage = parse_usage_event(self._fs.iter_lines(w.log))
                attribution = parse_attribution_event(self._fs.iter_lines(w.log))
                if not usage.has_result_line and (
                    attribution.recovered_input_tokens or attribution.recovered_output_tokens
                    or attribution.recovered_cache_read_tokens
                    or attribution.recovered_cache_creation_tokens
                ):
                    try:
                        model = self._store.get_node(w.step).model
                    except NodeNotFoundError:
                        model = None
                    usage = resolve_usage(usage, attribution, model, rates)
                resume = self._store.usage_accrual_state(w.spawnid)
                if resume is not None:
                    usage = _corrected_usage(usage, resume)
                    attribution = _corrected_attribution(attribution, resume)
                self._store.record_backfilled_usage(w.log, w.step, usage, attribution)
                self._store.clear_usage_accrual_state(w.spawnid)
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
        elif was_probing:
            stalled = []
            if not any_success:
                for w in pool.alive(probe):
                    signal = self._probe_signal(w, now)
                    if signal == "success":
                        any_success = True
                        break
                    if signal == "stalled":
                        stalled.append(w)
            if any_success:
                state = state.close()
                closed = True
            elif stalled:
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

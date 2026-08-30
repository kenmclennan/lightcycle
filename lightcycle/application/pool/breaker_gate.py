from dataclasses import dataclass, field
from typing import List

from lightcycle.domain.pool import Breaker, WorkerPool, parse_rate_limit_event
from lightcycle.domain.pool.worker_session import saw_terminal_command


@dataclass(frozen=True)
class BreakerGateResponse:
    breaker: Breaker
    opened: bool = False
    closed: bool = False
    rearmed: bool = False
    killed: List[str] = field(default_factory=list)


class BreakerGateUseCase:
    def __init__(self, workers, fs, breaker_port, config):
        self._workers = workers
        self._fs = fs
        self._breaker_port = breaker_port
        self._config = config

    def execute(self, now) -> BreakerGateResponse:
        state = Breaker.from_state(self._breaker_port.load())
        pool = WorkerPool.from_state(self._workers.workers_state())
        probe = self._workers.pid_alive
        was_probing = state.is_probing(now)

        rejected_reset_ats = []
        any_success = False
        for w in pool.dead_unchecked(probe):
            event = parse_rate_limit_event(self._fs.iter_lines(w.log))
            self._workers.mark_checked(w.spawnid)
            if event and event.is_rejected:
                rejected_reset_ats.append(event.reset_at)
            else:
                any_success = True

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

        self._breaker_port.save(state.as_dict())
        return BreakerGateResponse(
            breaker=state, opened=opened, closed=closed, rearmed=rearmed, killed=killed
        )

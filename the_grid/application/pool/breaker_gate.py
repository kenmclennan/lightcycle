from dataclasses import dataclass, field
from typing import List

from the_grid.domain.pool import Breaker, WorkerPool, parse_rate_limit_event


@dataclass(frozen=True)
class BreakerGateResponse:
    breaker: Breaker
    opened: bool = False
    closed: bool = False
    killed: List[str] = field(default_factory=list)


class BreakerGateUseCase:
    def __init__(self, workers, fs, breaker_port):
        self._workers = workers
        self._fs = fs
        self._breaker_port = breaker_port

    def execute(self, now) -> BreakerGateResponse:
        state = Breaker.from_state(self._breaker_port.load())
        pool = WorkerPool.from_state(self._workers.workers_state())
        probe = self._workers.pid_alive
        was_probing = state.is_probing(now)

        rejected_reset_ats = []
        any_success = False
        for w in pool.dead_unchecked(probe):
            event = parse_rate_limit_event(self._read_log(w.log))
            self._workers.mark_checked(w.spawnid)
            if event and event.is_rejected:
                rejected_reset_ats.append(event.reset_at)
            else:
                any_success = True

        opened = False
        closed = False
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

        self._breaker_port.save(state.as_dict())
        return BreakerGateResponse(breaker=state, opened=opened, closed=closed, killed=killed)

    def _read_log(self, path):
        data = self._fs.read_bytes(path)
        if data is None:
            return ""
        return data.decode("utf-8", errors="replace")

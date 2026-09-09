from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import Breaker


@dataclass(frozen=True)
class BreakerStatusResponse:
    is_open: bool
    reset_at: Optional[float]
    is_probing: bool
    pool_spin_open: bool = False


class BreakerStatusUseCase:
    def __init__(self, breaker_port, spin_port=None):
        self._breaker_port = breaker_port
        self._spin_port = spin_port

    def execute(self, now) -> BreakerStatusResponse:
        state = Breaker.from_state(self._breaker_port.load())
        pool_spin_open = False
        if self._spin_port is not None:
            pool_spin_open = self._spin_port.load().pool_tripped
        return BreakerStatusResponse(
            is_open=state.is_open, reset_at=state.reset_at, is_probing=state.is_probing(now),
            pool_spin_open=pool_spin_open,
        )

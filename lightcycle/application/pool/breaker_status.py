from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import Breaker


@dataclass(frozen=True)
class BreakerStatusResponse:
    is_open: bool
    reset_at: Optional[float]
    is_probing: bool


class BreakerStatusUseCase:
    def __init__(self, breaker_port):
        self._breaker_port = breaker_port

    def execute(self, now) -> BreakerStatusResponse:
        state = Breaker.from_state(self._breaker_port.load())
        return BreakerStatusResponse(
            is_open=state.is_open, reset_at=state.reset_at, is_probing=state.is_probing(now)
        )

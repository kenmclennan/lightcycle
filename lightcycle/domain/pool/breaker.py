from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Breaker:
    is_open: bool = False
    reset_at: Optional[float] = None
    trips: int = 0

    @classmethod
    def from_state(cls, d) -> "Breaker":
        return cls(
            is_open=bool(d.get("open", False)), reset_at=d.get("reset_at"),
            trips=int(d.get("trips", 0)),
        )

    def as_dict(self):
        return {"open": self.is_open, "reset_at": self.reset_at, "trips": self.trips}

    def is_probing(self, now):
        return self.is_open and self.reset_at is not None and now >= self.reset_at

    def spawn_cap(self, now, alive_count):
        if not self.is_open:
            return None
        if self.reset_at is None or now < self.reset_at:
            return 0
        return max(0, 1 - alive_count)

    def trip(self, reset_at) -> "Breaker":
        return Breaker(is_open=True, reset_at=reset_at, trips=1)

    def rearm(self, reset_at) -> "Breaker":
        return Breaker(is_open=True, reset_at=reset_at, trips=self.trips + 1)

    def close(self) -> "Breaker":
        return Breaker(is_open=False, reset_at=None)

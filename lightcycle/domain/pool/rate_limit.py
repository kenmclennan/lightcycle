from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RateLimitEvent:
    status: str
    reset_at: Optional[float] = None

    @property
    def is_rejected(self):
        return self.status == "rejected"

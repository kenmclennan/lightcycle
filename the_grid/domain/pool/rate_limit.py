import json
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RateLimitEvent:
    status: str
    reset_at: Optional[float] = None

    @property
    def is_rejected(self):
        return self.status == "rejected"


def parse_rate_limit_event(text) -> Optional[RateLimitEvent]:
    if not text:
        return None
    found = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("type") != "rate_limit_event":
            continue
        info = data.get("rate_limit_info") or {}
        status = info.get("status")
        if not status:
            continue
        found = RateLimitEvent(status=status, reset_at=info.get("resetsAt"))
    return found

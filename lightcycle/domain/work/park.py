from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Park:
    reason: Optional[str] = None
    needs: Optional[str] = None
    tried: Optional[str] = None

    def __bool__(self):
        return bool(self.reason or self.needs or self.tried)

    def as_dict(self) -> dict:
        return {"reason": self.reason, "needs": self.needs, "tried": self.tried}

    def as_history_note(self):
        fields = (("reason", self.reason), ("needs", self.needs), ("tried", self.tried))
        parts = [
            "%s=%s" % (name, " ".join(value.split())) for name, value in fields if value
        ]
        return "PARK RESOLVED: %s" % " | ".join(parts) if parts else None

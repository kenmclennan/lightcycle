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

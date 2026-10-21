from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ConfigReloadState:
    pid: Optional[int] = None
    outcome: Optional[str] = None
    reason: Optional[str] = None
    rejected_mtime: Optional[float] = None
    restart_required: Tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "pid": self.pid,
            "outcome": self.outcome,
            "reason": self.reason,
            "rejected_mtime": self.rejected_mtime,
            "restart_required": list(self.restart_required),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        return cls(
            pid=data.get("pid"),
            outcome=data.get("outcome"),
            reason=data.get("reason"),
            rejected_mtime=data.get("rejected_mtime"),
            restart_required=tuple(data.get("restart_required") or ()),
        )

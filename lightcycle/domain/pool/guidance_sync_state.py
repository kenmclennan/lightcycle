from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GuidanceSyncState:
    ok: bool = True
    at: Optional[float] = None
    detail: str = ""
    ref: Optional[str] = None

    def as_dict(self) -> dict:
        return {"ok": self.ok, "at": self.at, "detail": self.detail, "ref": self.ref}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        return cls(
            ok=data.get("ok", True),
            at=data.get("at"),
            detail=data.get("detail", ""),
            ref=data.get("ref"),
        )

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MemoryGateState:
    cap: Optional[int] = None
    pool_share: Optional[float] = None
    peak_worker_share: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "cap": self.cap,
            "pool_share": self.pool_share,
            "peak_worker_share": self.peak_worker_share,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        return cls(
            cap=data.get("cap"),
            pool_share=data.get("pool_share"),
            peak_worker_share=data.get("peak_worker_share"),
        )

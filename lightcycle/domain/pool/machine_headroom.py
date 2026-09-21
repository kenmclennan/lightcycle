from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MachineHeadroom:
    pool_share: Optional[float]
    peak_worker_share: Optional[float] = None

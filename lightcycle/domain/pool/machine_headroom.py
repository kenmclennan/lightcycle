from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MachineHeadroom:
    system_pressure: Optional[float]
    pool_share: Optional[float]

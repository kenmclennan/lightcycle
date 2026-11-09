from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lightcycle.domain.work import Item, SlowStep


@dataclass(frozen=True)
class ItemSignals:
    item: Item
    signals: Dict[str, Dict[str, int]]
    reflections: int
    durations: Dict[str, Optional[float]] = field(default_factory=dict)
    slow_steps: List[SlowStep] = field(default_factory=list)
    prs: int = 0
    prs_merged: int = 0
    layers: List[Dict[str, object]] = field(default_factory=list)

    def total_duration(self) -> Optional[float]:
        known = [v for v in self.durations.values() if v is not None]
        return sum(known) if known else None

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class NodeSpec:
    stage: Optional[str] = None
    role: Optional[str] = None
    item: Optional[str] = None
    deps: Tuple[str, ...] = ()
    previous: Optional[str] = None
    slice: int = 0

    def as_kwargs(self) -> dict:
        return {
            "stage": self.stage,
            "role": self.role,
            "item": self.item,
            "deps": list(self.deps),
            "previous": self.previous,
            "slice": self.slice,
        }

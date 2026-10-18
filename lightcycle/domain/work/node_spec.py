from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class NodeSpec:
    step: Optional[str] = None
    role: Optional[str] = None
    parent: Optional[str] = None
    deps: Tuple[str, ...] = ()
    previous: Optional[str] = None

    def as_kwargs(self) -> dict:
        return {
            "step": self.step,
            "role": self.role,
            "parent": self.parent,
            "deps": list(self.deps),
            "previous": self.previous,
        }

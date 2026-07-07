from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class NodeSpec:
    title: str
    step: Optional[str] = None
    role: Optional[str] = None
    parent: Optional[str] = None
    deps: Tuple[str, ...] = ()
    project: Optional[str] = None
    goal: Optional[str] = None

    def as_kwargs(self) -> dict:
        return {
            "title": self.title,
            "step": self.step,
            "role": self.role,
            "parent": self.parent,
            "deps": list(self.deps),
            "project": self.project,
            "goal": self.goal,
        }

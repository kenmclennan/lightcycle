"""TaskSpec: the description of a task to be created (a value object).

A blueprint, not a persisted task - it names the shape the application hands the
store to create work, replacing the bare dict that `next_task_spec` used to
return. It crosses to the store via as_kwargs() at the persistence boundary, the
same way Task/Artifact cross via as_dict.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class TaskSpec:
    title: str
    step: Optional[str] = None
    role: Optional[str] = None
    parent: Optional[str] = None
    deps: Tuple[str, ...] = ()
    project: Optional[str] = None
    goal: Optional[str] = None

    def as_kwargs(self) -> dict:
        return {
            "title": self.title, "step": self.step, "role": self.role,
            "parent": self.parent, "deps": list(self.deps),
            "project": self.project, "goal": self.goal,
        }

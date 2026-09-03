from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class Item:
    id: str
    artifacts: Tuple[Artifact, ...] = ()
    title: str = ""
    description: Optional[str] = None
    state: State = State.BACKLOGGED
    repo: Optional[str] = None
    project: Optional[str] = None
    workflow: Optional[str] = None
    outcome: Optional[str] = None
    deps: int = 0
    blocked_by: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    closed_at: Optional[str] = None

    @property
    def type(self):
        return "item"

    @property
    def parent(self):
        return None

    def artifact_of(self, atype, label=None):
        if label is None:
            for a in self.artifacts:
                if a.type == atype:
                    return a.value
            return None
        exact = next(
            (a.value for a in self.artifacts if a.type == atype and a.label == label), None
        )
        if exact is not None:
            return exact
        return next(
            (a.value for a in self.artifacts if a.type == atype and a.label is None), None
        )

    def present_types(self):
        return {a.type for a in self.artifacts}

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "repo": self.repo,
            "project": self.project,
            "workflow": self.workflow,
            "outcome": self.outcome,
            "artifacts": [a.as_dict() for a in self.artifacts],
            "deps": self.deps,
            "blocked_by": self.blocked_by,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
        }

from dataclasses import dataclass, field
from typing import List, Optional

from the_grid.domain.work.artifact import Artifact
from the_grid.domain.work.status import Status


@dataclass
class Task:
    id: str
    title: str = ""
    type: Optional[str] = None
    parent: Optional[str] = None
    role: Optional[str] = None
    step: Optional[str] = None
    status: Status = Status.READY
    project: Optional[str] = None
    goal: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    description: Optional[str] = None
    needs: Optional[str] = None
    outcome: Optional[str] = None
    deps: int = 0
    notes: Optional[str] = None
    claimed_by: Optional[str] = None
    epic: Optional[str] = None
    since: Optional[str] = None
    fired_at: Optional[str] = None
    closed_at: Optional[str] = None
    attention: bool = False

    def classify_for_human(self, flow):
        if not self.step:
            return ("triage", []) if self.attention else ("todo", [])
        outs = flow.outcomes_for(self.step)
        if flow.owner_of(self.step) == "human":
            return ("action", outs)
        return ("blocked", outs + ["unblock"])

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "parent": self.parent,
            "role": self.role,
            "step": self.step,
            "status": self.status,
            "project": self.project,
            "goal": self.goal,
            "artifacts": [a.as_dict() for a in self.artifacts],
            "description": self.description,
            "needs": self.needs, "outcome": self.outcome, "deps": self.deps,
            "notes": self.notes, "epic": self.epic, "attention": self.attention,
            "since": self.since, "fired_at": self.fired_at,
        }

"""Task: the work-item entity."""
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

    def classify_for_human(self, flow):
        """Classify this for:human task for tg inbox / tg backlog as (kind, outcomes):
        no step -> "todo" (backlog); a human-owned step -> "action" (inbox); an
        agent-owned step that has landed on the human (a block) -> "blocked" (inbox).
        Outcomes are the step's routes, plus "unblock" for a block."""
        if not self.step:
            return ("todo", [])
        outs = flow.outcomes_for(self.step)
        if flow.owner_of(self.step) == "human":
            return ("action", outs)
        return ("blocked", outs + ["unblock"])

    def as_dict(self) -> dict:
        """A plain serializable dict of the entity's fields (for JSON views and DTOs)."""
        return {
            "id": self.id, "title": self.title, "type": self.type, "parent": self.parent,
            "role": self.role, "step": self.step, "status": self.status,
            "project": self.project, "goal": self.goal,
            "artifacts": [a.as_dict() for a in self.artifacts],
            "description": self.description,
            "needs": self.needs, "outcome": self.outcome, "deps": self.deps,
            "notes": self.notes, "epic": self.epic,
        }

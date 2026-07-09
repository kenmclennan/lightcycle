from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.state import State


@dataclass
class Node:
    id: str
    title: str = ""
    type: Optional[str] = None
    parent: Optional[str] = None
    role: Optional[str] = None
    step: Optional[str] = None
    state: State = State.READY
    project: Optional[str] = None
    goal: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    description: Optional[str] = None
    needs: Optional[str] = None
    outcome: Optional[str] = None
    deps: int = 0
    notes: Optional[str] = None
    claimed_by: Optional[str] = None
    theme: Optional[str] = None
    since: Optional[str] = None
    fired_at: Optional[str] = None
    closed_at: Optional[str] = None
    attention: bool = False
    model: Optional[str] = None
    workflow: Optional[str] = None

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
            "state": self.state,
            "project": self.project,
            "goal": self.goal,
            "artifacts": [a.as_dict() for a in self.artifacts],
            "description": self.description,
            "needs": self.needs, "outcome": self.outcome, "deps": self.deps,
            "notes": self.notes, "theme": self.theme, "attention": self.attention,
            "since": self.since, "fired_at": self.fired_at, "closed_at": self.closed_at,
            "model": self.model,
        }

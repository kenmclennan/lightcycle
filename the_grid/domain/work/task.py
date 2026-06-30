"""Task: the work-item entity, plus the bead -> Task projection.

The bead projection (from_bead, label_value, labels, _status_of) is provisional: it
is the bd wire-format mapping and moves into BdStore (anti-corruption) in a later
batch, leaving the entity free of any store knowledge.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from the_grid.domain.work.artifact import Artifact
from the_grid.domain.work.status import Status


def labels(bead: dict) -> List[str]:
    return bead.get("labels") or []


def label_value(bead: dict, prefix: str) -> Optional[str]:
    for l in labels(bead):
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def _status_of(bead: dict, role: Optional[str]) -> Status:
    bd_status = bead.get("status")
    if bd_status == "closed":
        return Status.DONE
    if bead.get("assignee") or bd_status == "in_progress":
        return Status.IN_PROGRESS
    if role == "human":
        return Status.NEEDS_HUMAN
    return Status.READY


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
    needs: Optional[str] = None
    outcome: Optional[str] = None
    deps: int = 0
    notes: Optional[str] = None

    @classmethod
    def from_bead(cls, bead: dict) -> "Task":
        role = label_value(bead, "for:")
        meta = bead.get("metadata") or {}
        return cls(
            id=bead["id"], title=bead.get("title", ""),
            type=bead.get("issue_type"), parent=bead.get("parent"),
            role=role, step=label_value(bead, "step:"),
            status=_status_of(bead, role),
            project=label_value(bead, "project:"), goal=label_value(bead, "goal:"),
            artifacts=[Artifact.from_dict(a) for a in (meta.get("artifacts") or [])],
            needs=meta.get("needs"),
            outcome=bead.get("close_reason"),
            deps=bead.get("dependency_count") or 0,
            notes=bead.get("notes"),
        )

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
            "needs": self.needs, "outcome": self.outcome, "deps": self.deps,
            "notes": self.notes,
        }

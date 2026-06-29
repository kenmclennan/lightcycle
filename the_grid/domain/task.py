"""Task: the work-item entity, plus the bead -> Task projection.

Transitional during the Phase 4 dict->entity migration: Task is a dict subclass,
so existing `task["id"]` consumers keep working while new code reads typed
attributes (`task.id`). Consumers migrate folder-by-folder; the dict base is
dropped once they all use attributes.
"""
from typing import List, Optional

STATUS_DONE = "done"
STATUS_IN_PROGRESS = "in-progress"
STATUS_NEEDS_HUMAN = "needs-human"
STATUS_READY = "ready"


def labels(bead: dict) -> List[str]:
    return bead.get("labels") or []


def label_value(bead: dict, prefix: str) -> Optional[str]:
    for l in labels(bead):
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def _status_of(bead: dict, role: Optional[str]) -> str:
    bd_status = bead.get("status")
    if bd_status == "closed":
        return STATUS_DONE
    if bead.get("assignee") or bd_status == "in_progress":
        return STATUS_IN_PROGRESS
    if role == "human":
        return STATUS_NEEDS_HUMAN
    return STATUS_READY


class Task(dict):

    @classmethod
    def from_bead(cls, bead: dict) -> "Task":
        role = label_value(bead, "for:")
        meta = bead.get("metadata") or {}
        return cls({
            "id": bead["id"], "title": bead.get("title", ""),
            "type": bead.get("issue_type"), "parent": bead.get("parent"),
            "role": role, "step": label_value(bead, "step:"),
            "status": _status_of(bead, role),
            "project": label_value(bead, "project:"), "goal": label_value(bead, "goal:"),
            "artifacts": meta.get("artifacts") or [],
            "needs": meta.get("needs"),
            "outcome": bead.get("close_reason"),
            "deps": bead.get("dependency_count") or 0,
            "notes": bead.get("notes"),
        })

    def as_dict(self) -> dict:
        """A plain serializable dict of the entity's fields (for JSON views and
        DTO enrichment). Built from the typed attributes so it survives the eventual
        removal of the dict base."""
        return {
            "id": self.id, "title": self.title, "type": self.type, "parent": self.parent,
            "role": self.role, "step": self.step, "status": self.status,
            "project": self.project, "goal": self.goal, "artifacts": self.artifacts,
            "needs": self.needs, "outcome": self.outcome, "deps": self.deps,
            "notes": self.notes,
        }

    @property
    def id(self) -> str:
        return self["id"]

    @property
    def title(self) -> str:
        return self.get("title", "")

    @property
    def type(self) -> Optional[str]:
        return self.get("type")

    @property
    def parent(self) -> Optional[str]:
        return self.get("parent")

    @property
    def role(self) -> Optional[str]:
        return self.get("role")

    @property
    def step(self) -> Optional[str]:
        return self.get("step")

    @property
    def status(self) -> str:
        return self["status"]

    @property
    def project(self) -> Optional[str]:
        return self.get("project")

    @property
    def goal(self) -> Optional[str]:
        return self.get("goal")

    @property
    def artifacts(self) -> list:
        return self.get("artifacts") or []

    @property
    def needs(self) -> Optional[str]:
        return self.get("needs")

    @property
    def outcome(self) -> Optional[str]:
        return self.get("outcome")

    @property
    def deps(self) -> int:
        return self.get("deps") or 0

    @property
    def notes(self) -> Optional[str]:
        return self.get("notes")

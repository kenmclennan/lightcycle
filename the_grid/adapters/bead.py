"""The bd wire-format -> domain mapping (anti-corruption for the bead store).

This is the one place that knows bd's bead shape (labels, status strings, the
metadata block). It maps a raw bead dict to a Task so nothing past the store
adapters ever sees the wire format.
"""
from the_grid.domain.work import Artifact, Status, Task


def _labels(bead):
    return bead.get("labels") or []


def _label_value(bead, prefix):
    for l in _labels(bead):
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def _status_of(bead, role):
    bd_status = bead.get("status")
    if bd_status == "closed":
        return Status.DONE
    if bead.get("assignee") or bd_status == "in_progress":
        return Status.IN_PROGRESS
    if role == "human":
        return Status.NEEDS_HUMAN
    return Status.READY


def labels_for(*, role=None, step=None, project=None, goal=None):
    """Encode structured task/story attributes as bd labels (the write-side mapping)."""
    parts = []
    if role:
        parts.append("for:%s" % role)
    if step:
        parts.append("step:%s" % step)
    if project:
        parts.append("project:%s" % project)
    if goal:
        parts.append("goal:%s" % goal)
    return parts


def bead_to_task(bead):
    role = _label_value(bead, "for:")
    meta = bead.get("metadata") or {}
    return Task(
        id=bead["id"], title=bead.get("title", ""),
        type=bead.get("issue_type"), parent=bead.get("parent"),
        role=role, step=_label_value(bead, "step:"),
        status=_status_of(bead, role),
        project=_label_value(bead, "project:"), goal=_label_value(bead, "goal:"),
        artifacts=[Artifact.from_dict(a) for a in (meta.get("artifacts") or [])],
        needs=meta.get("needs"),
        outcome=bead.get("close_reason"),
        deps=bead.get("dependency_count") or 0,
        notes=bead.get("notes"),
        claimed_by=bead.get("assignee"),
    )

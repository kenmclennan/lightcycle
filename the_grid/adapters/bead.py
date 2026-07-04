from the_grid.domain.work import Artifact, Status, Task


def _labels(bead):
    return bead.get("labels") or []


def _label_value(bead, prefix):
    for l in _labels(bead):
        if l.startswith(prefix):
            return l[len(prefix) :]
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


def labels_for(*, role=None, step=None, project=None, goal=None, attention=False):
    parts = []
    if role:
        parts.append("for:%s" % role)
    if step:
        parts.append("step:%s" % step)
    if project:
        parts.append("project:%s" % project)
    if goal:
        parts.append("goal:%s" % goal)
    if attention:
        parts.append("attention")
    return parts


def bead_to_task(bead):
    role = _label_value(bead, "for:")
    meta = bead.get("metadata") or {}
    return Task(
        id=bead["id"],
        title=bead.get("title", ""),
        type=bead.get("issue_type"),
        parent=bead.get("parent"),
        role=role,
        step=_label_value(bead, "step:"),
        status=_status_of(bead, role),
        project=_label_value(bead, "project:"),
        goal=_label_value(bead, "goal:"),
        artifacts=[Artifact.from_dict(a) for a in (meta.get("artifacts") or [])],
        description=bead.get("description"),
        needs=meta.get("needs"),
        outcome=bead.get("close_reason"),
        deps=bead.get("dependency_count") or 0,
        notes=bead.get("notes"),
        claimed_by=bead.get("assignee"),
        epic=meta.get("epic"),
        since=meta.get("since"),
        fired_at=meta.get("fired_at"),
        closed_at=bead.get("closed_at"),
        attention="attention" in _labels(bead),
        model=meta.get("model"),
    )

import json

from the_grid.domain.work import Artifact, MigratedTask

_STRUCTURED_PREFIXES = ("for:", "step:", "project:", "goal:")


def _label_value(labels, prefix):
    for l in labels:
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def _other_labels(labels):
    return [
        l for l in labels
        if l != "attention" and not l.startswith(_STRUCTURED_PREFIXES)
    ]


def parse_bd_export_record(record: dict) -> MigratedTask:
    labels = record.get("labels") or []
    parent = None
    blocked_by = []
    for dep in record.get("dependencies") or []:
        if dep.get("type") == "parent-child":
            parent = dep.get("depends_on_id")
        elif dep.get("type") == "blocks":
            blocked_by.append(dep.get("depends_on_id"))
    meta = record.get("metadata") or {}
    return MigratedTask(
        id=record["id"],
        type=record.get("issue_type"),
        title=record.get("title", ""),
        status=record.get("status") or "open",
        parent=parent,
        role=_label_value(labels, "for:"),
        step=_label_value(labels, "step:"),
        project=_label_value(labels, "project:"),
        goal=_label_value(labels, "goal:"),
        attention="attention" in labels,
        assignee=record.get("assignee"),
        notes=record.get("notes"),
        outcome=record.get("close_reason"),
        artifacts=[Artifact.from_dict(a) for a in (meta.get("artifacts") or [])],
        blocked_by=blocked_by,
        labels=_other_labels(labels),
        since=meta.get("since"),
        fired_at=meta.get("fired_at"),
        closed_at=record.get("closed_at"),
        created_at=record.get("created_at"),
    )


def parse_bd_export_lines(lines):
    return [parse_bd_export_record(json.loads(line)) for line in lines if line.strip()]

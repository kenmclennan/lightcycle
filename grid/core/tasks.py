"""Pure task model: bead -> task projection, status mapping, bucketing, filters."""


def labels(bead):
    return bead.get("labels") or []


def label_value(bead, prefix):
    for l in labels(bead):
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def task_from_bead(bead):
    role = label_value(bead, "for:")
    bd_status = bead.get("status")
    assignee = bead.get("assignee")
    if bd_status == "closed":
        status = "done"
    elif assignee or bd_status == "in_progress":
        status = "in-progress"
    elif role == "human":
        status = "needs-human"
    else:
        status = "ready"
    return {
        "id": bead["id"], "title": bead.get("title", ""),
        "type": bead.get("issue_type"), "parent": bead.get("parent"),
        "role": role, "step": label_value(bead, "step:"),
        "status": status,
        "project": label_value(bead, "project:"), "goal": label_value(bead, "goal:"),
        "artifacts": (bead.get("metadata") or {}).get("artifacts") or [],
        "outcome": bead.get("close_reason"),
        "deps": bead.get("dependency_count") or 0,
    }


def filter_by_status(tasks, status):
    return [t for t in tasks if t["status"] == status]


def bucket(tasks):
    buckets = {"mine": [], "active": [], "queue": [], "blocked": [], "done": []}
    for t in tasks:
        if t["status"] == "done":
            buckets["done"].append(t)
        elif t["status"] == "in-progress":
            buckets["active"].append(t)
        elif t["status"] == "needs-human":
            buckets["mine"].append(t)
        elif t["status"] == "ready":
            buckets["queue"].append(t)
        else:
            buckets["blocked"].append(t)
    return buckets

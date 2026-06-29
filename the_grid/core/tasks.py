"""Task buckets and filters over the Task entity.

The Task entity and the bead -> Task projection now live in
`the_grid.domain.task`; this module keeps the status-based grouping helpers and
re-exports the projection + label helpers for existing importers.
"""
from the_grid.domain.task import Task, label_value, labels  # noqa: F401

task_from_bead = Task.from_bead


def filter_by_status(tasks, status):
    return [t for t in tasks if t["status"] == status]


def classify_mine(task, owner, routes):
    """Classify a for:human task for `tg inbox` / `tg backlog`. Returns (kind, outcomes):
    no step -> "todo" (backlog); a human-owned step -> "action" (inbox); an agent-owned
    step that has landed on the human (a block) -> "blocked" (inbox). Outcomes are the
    step's routes, plus `unblock` for a block (the way to hand it back to the agent)."""
    step = task.get("step")
    if not step:
        return "todo", []
    outs = sorted((routes.get(step) or {}).keys())
    if owner.get(step) == "human":
        return "action", outs
    return "blocked", outs + ["unblock"]


def partition_mine(tasks, owner, routes, kinds, n=None):
    """Classify for:human tasks, keep those whose kind is in `kinds`, sort by id, limit to n."""
    classified = [(classify_mine(t, owner, routes), t) for t in tasks]
    filtered = [(cls, t) for cls, t in classified if cls[0] in kinds]
    filtered.sort(key=lambda r: r[1]["id"])
    return filtered[:n] if n is not None else filtered


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

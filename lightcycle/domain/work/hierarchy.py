from dataclasses import dataclass

from lightcycle.domain.work.step import Step
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class HierarchyRow:
    node: Step
    depth: int


def compose_hierarchy(root, steps_by_item):
    rows = [HierarchyRow(root, 0)]
    for step in steps_by_item.get(root.id, []):
        rows.append(HierarchyRow(step, 1))
    return rows


def landing_tab(node):
    if node.type == "item":
        return "description"
    return "log" if node.state == State.IN_PROGRESS else "detail"


def row_bucket(node, flow):
    if node.state == State.DONE:
        return "done"
    if node.state == State.IN_PROGRESS:
        return "active"
    if node.state == State.READY and getattr(node, "role", None) == "human":
        kind, _outs = node.classify_for_human(flow)
        return "escalation" if kind == "blocked" else "gate"
    return "queued"


def display_role(role):
    return role or "human"


def display_stage(phrase, stage):
    return "%s · %s" % (phrase, stage) if phrase else stage


def park_resume_command(node_id):
    return "lc set %s --state ready" % node_id


def viewable_artifacts(node):
    return [a for a in getattr(node, "artifacts", ()) if not a.internal]

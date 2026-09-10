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


def row_bucket(node, flow):
    if node.state == State.DONE:
        return "done"
    if node.state == State.RUNNING:
        return "active"
    if node.state == State.WAITING and is_human_step(node):
        kind, _outs = node.classify_for_human(flow)
        return "escalation" if kind == "blocked" else "gate"
    if node.state == State.WAITING:
        return "gate"
    return "queued"


def is_human_step(node):
    return node.type == "step" and (node.role or "human") == "human"


def viewable_artifacts(node):
    return [a for a in getattr(node, "artifacts", ()) if not a.internal]

from dataclasses import dataclass

from lightcycle.domain.work.node import Node
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class HierarchyRow:
    node: Node
    depth: int


def compose_hierarchy(root, items, steps_by_item):
    rows = [HierarchyRow(root, 0)]
    if root.type == "theme":
        for item in items:
            rows.append(HierarchyRow(item, 1))
            for step in steps_by_item.get(item.id, []):
                rows.append(HierarchyRow(step, 2))
    else:
        for step in steps_by_item.get(root.id, []):
            rows.append(HierarchyRow(step, 1))
    return rows


def landing_tab(node):
    if node.type == "theme":
        return "hierarchy"
    if node.state == State.IN_PROGRESS:
        return "log"
    if node.state == State.DONE:
        return "artifacts"
    if node.state == State.READY and node.role == "human":
        return "artifacts"
    return "hierarchy"


def row_bucket(node):
    if node.state == State.DONE:
        return "done"
    if node.state == State.IN_PROGRESS:
        return "active"
    if node.state == State.READY and node.role == "human":
        return "needs-attention"
    return "queued"


def display_role(role):
    return role or "human"


def has_content(node):
    return any(not a.internal for a in node.artifacts)


def viewable_artifacts(node):
    return [a for a in node.artifacts if not a.internal]

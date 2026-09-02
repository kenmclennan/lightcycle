from dataclasses import dataclass

from lightcycle.domain.work.node import Node
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class HierarchyRow:
    node: Node
    depth: int


def compose_hierarchy(root, steps_by_item):
    rows = [HierarchyRow(root, 0)]
    for step in steps_by_item.get(root.id, []):
        rows.append(HierarchyRow(step, 1))
    return rows


def landing_tab(node):
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


def display_stage(phrase, stage):
    return "%s · %s" % (phrase, stage) if phrase else stage


def park_resume_command(node_id):
    return "lc set %s --state ready" % node_id


def has_content(node):
    return any(not a.internal for a in node.artifacts)


def viewable_artifacts(node):
    return [a for a in node.artifacts if not a.internal]

from dataclasses import dataclass

from lightcycle.domain.runs import Pass
from lightcycle.domain.work.step import Step
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class HierarchyRow:
    node: Step
    depth: int


@dataclass(frozen=True)
class PassHeader:
    pass_record: Pass

    @property
    def id(self):
        return self.pass_record.id

    @property
    def type(self):
        return "pass"

    @property
    def title(self):
        return "Pass %d" % self.pass_record.n

    @property
    def state(self):
        return State.DONE if self.pass_record.state == "closed" else State.IN_PROGRESS

    @property
    def blocked_by(self):
        return []


def compose_hierarchy(root, steps_by_item, passes_by_item):
    passes = {p.id: p for p in passes_by_item.get(root.id, ())}
    rows = [HierarchyRow(root, 0)]
    current = None
    for step in steps_by_item.get(root.id, []):
        pid = step.pass_id if step.pass_id in passes else None
        if pid != current and pid is not None:
            rows.append(HierarchyRow(PassHeader(passes[pid]), 1))
        current = pid
        rows.append(HierarchyRow(step, 2 if pid is not None else 1))
    return rows


def landing_tab(node):
    if node.type == "item":
        return "description"
    return "log" if node.state == State.IN_PROGRESS else "detail"


def row_bucket(node):
    if node.state == State.DONE:
        return "done"
    if node.state == State.IN_PROGRESS:
        return "active"
    if node.state == State.READY and getattr(node, "role", None) == "human":
        return "needs-attention"
    return "queued"


def display_role(role):
    return role or "human"


def display_stage(phrase, stage):
    return "%s · %s" % (phrase, stage) if phrase else stage


def park_resume_command(node_id):
    return "lc set %s --state ready" % node_id


def has_content(node):
    return any(not a.internal for a in getattr(node, "artifacts", ()))


def viewable_artifacts(node):
    return [a for a in getattr(node, "artifacts", ()) if not a.internal]

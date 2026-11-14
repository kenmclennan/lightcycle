from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.work.step import Step
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class CalloutLine:
    callout_id: str
    status: str
    wait: bool
    started: Optional[float]
    finished: Optional[float]


@dataclass(frozen=True)
class HierarchyRow:
    node: Step
    depth: int
    callout: Optional[CalloutLine] = None

    @property
    def row_key(self):
        if self.callout is None:
            return self.node.id
        return "callout:%s:%s" % (self.node.id, self.callout.callout_id)


def callout_line(callout_id, record):
    return CalloutLine(
        callout_id=callout_id,
        status=record.get("status"),
        wait=bool(record.get("wait")),
        started=record.get("started"),
        finished=record.get("finished"),
    )


def compose_hierarchy(root, steps_by_item, callouts_by_step=None):
    callouts_by_step = callouts_by_step or {}
    rows = [HierarchyRow(root, 0)]
    for step in steps_by_item.get(root.id, []):
        rows.append(HierarchyRow(step, 1))
        for line in callouts_by_step.get(step.id, []):
            rows.append(HierarchyRow(step, 2, line))
    return rows


def row_bucket(node, flow, pool_running):
    if node.state == State.DONE:
        return "done"
    if node.state == State.RUNNING:
        return "active"
    if node.state == State.QUEUED and is_engine_step(node) and pool_running:
        return "active"
    if node.state == State.WAITING and is_human_step(node):
        kind, _outs = node.classify_for_human(flow)
        return "escalation" if kind == "blocked" else "gate"
    if node.state == State.WAITING:
        return "gate"
    return "queued"


def is_human_step(node):
    return node.type == "step" and (node.role or "human") == "human"


def is_engine_step(node):
    return node.type == "step" and node.role == "engine"

from dataclasses import dataclass
from typing import Any, List

from lightcycle.domain.work import row_bucket


@dataclass(frozen=True)
class SelectedRow:
    node: Any
    owning_node: Any
    flow: Any


@dataclass(frozen=True)
class PrioritySelection:
    attention: List[SelectedRow]
    active: List[SelectedRow]
    queued: List[SelectedRow]


def select_priority_rows(store, lanes, flow_service):
    claimed = set()
    attention, active, queued = [], [], []
    runnable = [n for n in lanes["queue"] if not n.blocked_by]
    held = [n for n in lanes["queue"] if n.blocked_by]
    inbox = sorted(
        ((n, flow_service.flow_for(n)) for n in lanes["inbox"]),
        key=lambda pair: row_bucket(pair[0], pair[1]) != "escalation",
    )
    for group_rows, nodes_and_flow in (
        (attention, inbox),
        (active, [(n, flow_service.flow_for(n)) for n in lanes["active"]]),
        (queued, [(n, flow_service.flow_for(n)) for n in runnable]
         + [(n, flow_service.flow_for(n)) for n in held]),
    ):
        for node, flow in nodes_and_flow:
            owning_id = node.parent or node.id
            if owning_id in claimed:
                continue
            claimed.add(owning_id)
            group_rows.append(
                SelectedRow(node=node, owning_node=store.get_node(owning_id), flow=flow)
            )
    return PrioritySelection(attention=attention, active=active, queued=queued)

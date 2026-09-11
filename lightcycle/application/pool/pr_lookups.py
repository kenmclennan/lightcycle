import datetime

from lightcycle.domain.work import State, node_id_key, parse_timestamp
from lightcycle.ports.github import ReadFailure

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def false_on_failure(result):
    return False if isinstance(result, ReadFailure) else result


def flow_for(flow_service, node):
    return flow_service.flow_for(node)


def run_of(store, flow_service, node):
    phase = flow_for(flow_service, node).step_def(getattr(node, "stage", None)).phase
    return store.current_run(node.item, phase)


def active_step_at(store, item_id, stage):
    for child in store.children(item_id):
        if child.type == "step" and child.state != State.DONE and child.stage == stage:
            return child
    return None


def active_step_any(store, item_id):
    for child in store.children(item_id):
        if child.type == "step" and child.state != State.DONE:
            return child
    return None


def latest_step(store, item_id):
    steps = sorted(
        store.children(item_id),
        key=lambda s: (parse_timestamp(s.created_at) or _MIN_TIMESTAMP, node_id_key(s.id)),
    )
    return steps[-1] if steps else None

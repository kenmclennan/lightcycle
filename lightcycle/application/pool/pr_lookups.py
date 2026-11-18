import datetime

from lightcycle.domain.work import State, node_id_key, parse_timestamp
from lightcycle.ports.github import ReadFailure

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def false_on_failure(result):
    return False if isinstance(result, ReadFailure) else result


def flow_for(flow_service, node):
    return flow_service.flow_for(node)


def skip_unpinned(store, flow_service, node):
    value = flow_service.unpinned_workflow(node)
    if value is None:
        return False
    target = node if node.type == "step" else active_step_any(store, node.id)
    if target is not None:
        store.note_condition(
            target.id,
            "workflow %s is not a pin; set it with lc set %s --workflow %s"
            % (value, node.item if node.type == "step" else node.id, value),
        )
    return True


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


def active_step_in_phase(store, flow_service, item_id, phase):
    for child in store.children(item_id):
        if (
            child.type == "step"
            and child.state != State.DONE
            and flow_service.phase_for(child) == phase
        ):
            return child
    return None


def latest_step(store, item_id):
    steps = sorted(
        store.children(item_id),
        key=lambda s: (parse_timestamp(s.created_at) or _MIN_TIMESTAMP, node_id_key(s.id)),
    )
    return steps[-1] if steps else None


def latest_artifact(store, step_id, atype):
    found = None
    for artifact in store.item_artifacts(step_id):
        if artifact.type == atype:
            found = artifact.value
    return found


def latest_judged_artifact(store, flow, step, atype):
    phase = flow.step_def(step.stage).phase
    latest = None
    latest_key = None
    for child in store.children(step.item):
        if child.type != "step" or child.state != State.DONE:
            continue
        sd = flow.step_def(child.stage)
        if sd.phase != phase or (sd.ci_success is None and sd.ci_failure is None):
            continue
        key = (parse_timestamp(child.created_at) or _MIN_TIMESTAMP, node_id_key(child.id))
        if latest_key is None or key > latest_key:
            latest, latest_key = child, key
    if latest is None:
        return None
    return latest_artifact(store, latest.id, atype)

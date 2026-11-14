import datetime

from lightcycle.domain.work.node_id import node_id_key
from lightcycle.domain.work.timestamp import parse_timestamp

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def step_order_key(step):
    return (parse_timestamp(step.created_at) or _MIN_TIMESTAMP, node_id_key(step.id))


def stage_escalation_firing_ids(store, flow, item, stage, history):
    step_def = flow.step_def(stage)
    done = {s.id: s for s in history}
    firing = set()
    for cap in step_def.caps.values():
        target = cap.escalate_stage
        if target is None or step_def.routes.get(cap.outcome) == target:
            continue
        for e in store.steps_at_step(target):
            prior = done.get(e.previous_step)
            if e.item == item and prior is not None and prior.outcome == cap.outcome:
                firing.add(prior.id)
    return firing


def last_gate_firing_key(flow, stage, history):
    outcomes = {
        c.escalate_outcome for c in flow.step_def(stage).caps.values() if c.escalate_outcome
    }
    keys = [step_order_key(s) for s in history if s.outcome in outcomes]
    return max(keys) if keys else None

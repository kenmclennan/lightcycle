from lightcycle.domain.work.callout_runs import CALLOUT_RUNS, holds_gate, parse_runs


def callout_runs_of(store, step_id):
    found = None
    for artifact in store.item_artifacts(step_id):
        if artifact.type == CALLOUT_RUNS:
            found = artifact.value
    return parse_runs(found)


def callout_hold_step_ids(store):
    held = set()
    for step in store.all_steps():
        if any(holds_gate(r) for r in callout_runs_of(store, step.id).values()):
            held.add(step.id)
    return held

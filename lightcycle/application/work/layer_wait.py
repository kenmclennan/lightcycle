from lightcycle.domain.work.layer_ci_wait import LAYER_CI_WAIT


def layer_wait_step_ids(store):
    waiting = set()
    for step in store.all_steps():
        if step.park.needs:
            continue
        if any(a.type == LAYER_CI_WAIT for a in store.item_artifacts(step.id)):
            waiting.add(step.id)
    return waiting

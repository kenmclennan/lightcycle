SLACK_SECONDS = 1.0


def _epoch(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def feedback_window_start(run, last_push):
    dispatched = _epoch(run.comments_dispatched_through)
    if dispatched > 0:
        return max(0.0, dispatched - SLACK_SECONDS)
    return last_push


def already_admitted_keys(store, feedback_step, item):
    keys = set()
    for step in store.steps_at_step(feedback_step):
        if step.item != item:
            continue
        for artifact in store.item_artifacts(step.id):
            if artifact.type == "admitted-comments":
                keys.update(k for k in artifact.value.split("\n") if k)
    return keys


def feedback_stage_of(flow, poll_step):
    phase = flow.step_def(poll_step.stage).phase
    for stage in flow.steps():
        step_def = flow.step_def(stage)
        if step_def.pr_feedback and step_def.phase == phase:
            return step_def
    return None

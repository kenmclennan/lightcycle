def planned_path(flow, from_step):
    path = []
    stage = from_step
    visited = {stage}
    while True:
        outcome = _normal_outcome(flow, stage)
        if outcome is None:
            break
        transition = flow.next(stage, outcome)
        if transition is None or transition.to_step in visited:
            break
        path.append((transition.to_step, transition.to_role))
        visited.add(transition.to_step)
        stage = transition.to_step
    return path


def _normal_outcome(flow, stage):
    outcomes = flow.outcomes_for(stage)
    if len(outcomes) == 1:
        return outcomes[0]
    merge = flow.merge_outcome(stage)
    if merge is not None:
        return merge
    cap_outcome = flow.ci_failed_cap_outcome(stage)
    if cap_outcome is not None:
        remaining = [o for o in outcomes if o != cap_outcome]
        if len(remaining) == 1:
            return remaining[0]
    primary = flow.primary_outcome(stage)
    if primary is not None:
        return primary
    return None

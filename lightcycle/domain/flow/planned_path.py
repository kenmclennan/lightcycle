def planned_path(flow, from_stage):
    path = []
    stage = from_stage
    visited = {stage}
    while True:
        outcome = _normal_outcome(flow, stage)
        if outcome is None:
            break
        transition = flow.next(stage, outcome)
        if transition is None or transition.to_stage in visited:
            break
        path.append((transition.to_stage, transition.to_role))
        visited.add(transition.to_stage)
        stage = transition.to_stage
    return path


def _normal_outcome(flow, stage):
    sd = flow.step_def(stage)
    outcomes = sorted(sd.routes.keys())
    if len(outcomes) == 1:
        return outcomes[0]
    merge = sd.pr_merge
    if merge is not None:
        return merge
    cap_outcome = sd.ci_cap.outcome if sd.ci_cap else None
    if cap_outcome is not None:
        remaining = [o for o in outcomes if o != cap_outcome]
        if len(remaining) == 1:
            return remaining[0]
    primary = sd.primary
    if primary is not None:
        return primary
    return None

def _successors(flow, stage):
    step = flow.step_def(stage)
    targets = [t for t in step.routes.values() if t]
    for target in [step.pr_feedback] + [c.escalate_stage for c in step.caps.values()]:
        if target:
            targets.append(target)
    return targets


def remaining_stages(flow, entry, open_steps):
    remaining = set()
    frontier = []
    if not open_steps:
        if entry:
            remaining.add(entry)
            frontier.append(entry)
    for stage, running in open_steps:
        if not running:
            remaining.add(stage)
        frontier.append(stage)
    while frontier:
        stage = frontier.pop()
        for target in _successors(flow, stage):
            if target not in remaining:
                remaining.add(target)
                frontier.append(target)
    return remaining

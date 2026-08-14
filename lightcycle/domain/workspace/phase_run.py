def current_run_index(phases):
    ordered = list(phases)
    if not ordered:
        return 1
    target = ordered[-1]
    if target is None:
        return 1
    runs = 0
    previous = object()
    for phase in ordered:
        if phase == target and previous != target:
            runs += 1
        previous = phase
    return runs or 1


def phase_key(phase, run_index):
    if phase is None or run_index <= 1:
        return phase
    return "%s-%d" % (phase, run_index)

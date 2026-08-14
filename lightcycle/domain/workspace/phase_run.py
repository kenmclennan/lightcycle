def runs_of(phases, target):
    if target is None:
        return 0
    runs = 0
    previous = object()
    for phase in phases:
        if phase == target and previous != target:
            runs += 1
        previous = phase
    return runs


def current_run_index(phases):
    ordered = list(phases)
    if not ordered or ordered[-1] is None:
        return 1
    return runs_of(ordered, ordered[-1]) or 1


def phase_key(phase, run_index):
    if phase is None or run_index <= 1:
        return phase
    return "%s-%d" % (phase, run_index)

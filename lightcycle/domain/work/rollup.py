from lightcycle.domain.work.state import State


def roll_up(children_states):
    children_states = list(children_states)
    if not children_states:
        return State.BACKLOGGED
    if all(s == State.DONE for s in children_states):
        return State.DONE
    for s in (State.WAITING, State.RUNNING, State.QUEUED, State.BLOCKED):
        if s in children_states:
            return s
    return State.BACKLOGGED

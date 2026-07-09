from lightcycle.domain.work.state import State


def roll_up(children_states):
    children_states = list(children_states)
    if not children_states:
        return State.BACKLOGGED
    if all(s == State.DONE for s in children_states):
        return State.DONE
    if any(s == State.DONE for s in children_states):
        return State.IN_PROGRESS
    if any(s == State.IN_PROGRESS for s in children_states):
        return State.IN_PROGRESS
    return State.READY

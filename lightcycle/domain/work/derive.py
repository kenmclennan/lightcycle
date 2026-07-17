from lightcycle.domain.work.rollup import roll_up
from lightcycle.domain.work.state import State


def derive_state(node_type, closed, assignee, has_unresolved_deps, child_states):
    if closed:
        return State.DONE
    if node_type != "step":
        return roll_up(child_states)
    if assignee:
        return State.IN_PROGRESS
    if has_unresolved_deps:
        return State.BACKLOGGED
    return State.READY

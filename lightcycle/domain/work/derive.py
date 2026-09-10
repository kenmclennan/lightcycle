from lightcycle.domain.work.rollup import roll_up
from lightcycle.domain.work.state import State


def role_state(role):
    return State.WAITING if role is None or role == "human" else State.QUEUED


def derive_state(node_type, closed, assignee, has_unresolved_deps, role, child_states):
    if closed:
        return State.DONE
    if node_type != "step":
        if has_unresolved_deps:
            return State.BLOCKED
        return roll_up(child_states)
    if assignee:
        return State.RUNNING
    if has_unresolved_deps:
        return State.BLOCKED
    return role_state(role)

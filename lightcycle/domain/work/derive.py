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


def item_blocked_by(item_id, own_blockers, child_state, step_blockers):
    blockers = set(own_blockers)
    if child_state == State.BLOCKED:
        step_ids = {step_id for step_id, _ in step_blockers}
        for _, step_blocked_by in step_blockers:
            blockers.update(b for b in step_blocked_by if b != item_id and b not in step_ids)
    return sorted(blockers)

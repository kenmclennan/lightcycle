from dataclasses import dataclass
from typing import Optional

FIELDS_BY_TYPE = {
    "item": frozenset(
        {"title", "description", "project", "workflow", "label", "backlog", "step", "depends"}
    ),
    "step": frozenset({"title", "notes", "needs", "reason", "tried", "label"}),
}

REQUIRED_WITH_STATE = {
    "waiting": ("needs", "reason"),
}

STATES_BY_TYPE = {
    "item": frozenset({"active", "in_progress"}),
    "step": frozenset({"ready", "waiting"}),
}


@dataclass(frozen=True)
class FieldRefusal:
    fields: tuple
    requested_type: str
    owner: Optional[str]


@dataclass(frozen=True)
class StateRefusal:
    state: str
    requested_type: str
    owner: Optional[str]
    allowed: tuple


def owner_of_field(field):
    for node_type, fields in FIELDS_BY_TYPE.items():
        if field in fields:
            return node_type
    return None


def owner_of_state(state):
    for node_type, states in STATES_BY_TYPE.items():
        if state in states:
            return node_type
    return None


def all_states():
    return sorted(s for states in STATES_BY_TYPE.values() for s in states)


def refuse_fields(node_type, fields):
    wrong = tuple(sorted(f for f in fields if f not in FIELDS_BY_TYPE[node_type]))
    if not wrong:
        return None
    return FieldRefusal(fields=wrong, requested_type=node_type, owner=owner_of_field(wrong[0]))


def refuse_state(node_type, state):
    if state is None or state in STATES_BY_TYPE[node_type]:
        return None
    owner = owner_of_state(state)
    if owner is None:
        return StateRefusal(
            state=state, requested_type=node_type, owner=None, allowed=tuple(all_states())
        )
    return StateRefusal(
        state=state, requested_type=node_type, owner=owner,
        allowed=tuple(sorted(STATES_BY_TYPE[node_type])),
    )


def missing_for_state(state, given):
    return [f for f in REQUIRED_WITH_STATE.get(state, ()) if f not in given]

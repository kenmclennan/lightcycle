from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.work.state import ALIASES, State

FIELDS_BY_TYPE = {
    "item": frozenset(
        {"title", "description", "project", "workflow", "label", "backlog", "step", "depends"}
    ),
    "step": frozenset({"title", "notes", "needs", "reason", "tried", "label"}),
}

DONE_FIELDS_BY_TYPE = {
    "step": frozenset({"note"}),
    "item": frozenset({"note", "disposition"}),
}

REQUIRED_WITH_STATE = {
    "waiting": ("needs", "reason"),
}

STATES_BY_TYPE = {
    "item": frozenset({"active", ALIASES[State.RUNNING]}),
    "step": frozenset({ALIASES[State.WAITING], State.WAITING.value}),
}

ALLOWED_STATES_BY_FLAG = {
    "title": (None,), "description": (None,), "project": (None,),
    "label": (None,), "backlog": (None,), "notes": (None,),
    "workflow": (None, "active"),
    "step": ("active",),
    "depends": ("active",),
    "needs": (State.WAITING.value,), "reason": (State.WAITING.value,),
    "tried": (State.WAITING.value,),
    "unset": (None,),
}

UNSETTABLE_FIELDS = ("description", "project", "workflow", "notes")

UNSET_REFUSAL_REASONS = {
    "title": "a title must not be blank; there is nothing to clear, only to replace",
    "label": "there is no way to clear a label this way",
    "needs": "a park's fields are cleared as a whole, via --state ready",
    "reason": "a park's fields are cleared as a whole, via --state ready",
    "tried": "a park's fields are cleared as a whole, via --state ready",
    "backlog": "backlog is a list of ids to resolve, not a value to clear",
    "step": "step is a one-shot input to activation, not a persisted field",
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


def owner_of_field(field, table=FIELDS_BY_TYPE):
    for node_type, fields in table.items():
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


def refuse_fields(node_type, fields, table=FIELDS_BY_TYPE):
    wrong = tuple(sorted(f for f in fields if f not in table[node_type]))
    if not wrong:
        return None
    return FieldRefusal(
        fields=wrong, requested_type=node_type, owner=owner_of_field(wrong[0], table)
    )


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


def _named_type(node_type):
    return "an item" if node_type == "item" else "a step"


def render_field_refusal(refusal):
    named = ", ".join("--%s" % f for f in refusal.fields)
    verb = "belong" if len(refusal.fields) > 1 else "belongs"
    if refusal.owner is None:
        return "%s %s to no structure" % (named, verb)
    return "%s %s to %s, not %s" % (
        named, verb, _named_type(refusal.owner), _named_type(refusal.requested_type),
    )

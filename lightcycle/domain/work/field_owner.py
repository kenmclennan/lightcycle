FIELDS_BY_TYPE = {
    "item": frozenset(
        {"title", "description", "project", "workflow", "label", "backlog", "step"}
    ),
    "step": frozenset({"title", "notes", "needs", "reason", "tried", "label"}),
}

STATES_BY_TYPE = {
    "item": frozenset({"active", "in_progress"}),
    "step": frozenset({"ready", "blocked"}),
}


def _named(node_type):
    return "an item" if node_type == "item" else "a step"


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
    wrong = sorted(f for f in fields if f not in FIELDS_BY_TYPE[node_type])
    if not wrong:
        return None
    named = ", ".join("--%s" % f for f in wrong)
    verb = "belong" if len(wrong) > 1 else "belongs"
    owner = owner_of_field(wrong[0])
    if owner is None:
        return "%s %s to no structure" % (named, verb)
    return "%s %s to %s, not %s" % (named, verb, _named(owner), _named(node_type))


def refuse_state(node_type, state):
    if state is None or state in STATES_BY_TYPE[node_type]:
        return None
    owner = owner_of_state(state)
    if owner is None:
        return "unknown --state %r; use %s" % (state, ", ".join(all_states()))
    takes = ", ".join("--state %s" % s for s in sorted(STATES_BY_TYPE[node_type]))
    return "--state %s applies to %s, not %s; %s takes %s" % (
        state, _named(owner), _named(node_type), _named(node_type), takes)

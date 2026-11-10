import re

from lightcycle.domain.work.gate_hold import GATE_HOLD, HELD_PREFIX

_TRAILER = re.compile(r" \(x\d+, last [^)]*\)$")


class GateHold:
    def __init__(self, store):
        self._store = store

    def note_of(self, step_id):
        found = None
        for artifact in self._store.item_artifacts(step_id):
            if artifact.type == GATE_HOLD:
                found = artifact.value
        return found if found and found.strip() else None

    def is_held(self, step_id):
        return any(a.type == GATE_HOLD for a in self._store.item_artifacts(step_id))

    def place(self, step_id, note):
        self._store.replace_artifact(step_id, GATE_HOLD, note, internal=True)

    def lift(self, step_id):
        self._store.remove_artifact(step_id, GATE_HOLD)
        self._store.clear_condition(step_id, HELD_PREFIX)

    def observe(self, step, text):
        line = "%s %s" % (HELD_PREFIX, " ".join(text.split()))
        for existing in (self._store.get_node(step.id).notes or "").splitlines():
            if existing.startswith(HELD_PREFIX) and _TRAILER.sub("", existing) == line:
                return
        self._store.note_condition(step.id, line)


def route_name(flow, step, outcome):
    return flow.step_def(step.stage).routes.get(outcome) or outcome

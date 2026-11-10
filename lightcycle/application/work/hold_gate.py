from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.gate_hold import GateHold
from lightcycle.domain.work import State


@dataclass(frozen=True)
class HoldGateInput:
    target: str
    note: str


@dataclass(frozen=True)
class HoldGateResponse:
    step: str
    note: str


def resolve_gate_step(store, target, verb):
    kind = store.type_of(target)
    if kind is None:
        raise UseCaseError("unknown node '%s'" % target)
    if kind == "step":
        return store.get_node(target)
    if kind != "item":
        raise UseCaseError("'%s' is not an item or a step (type=%s)" % (target, kind))
    gates = [
        c for c in store.children(target)
        if c.type == "step" and c.state == State.WAITING and c.role == "human"
    ]
    if verb == "release":
        held = GateHold(store)
        gates = [c for c in store.children(target) if c.type == "step" and held.is_held(c.id)]
        if not gates:
            raise UseCaseError("%s has no held gate to release" % target)
    elif not gates:
        raise UseCaseError("%s has no waiting human gate to hold" % target)
    if len(gates) > 1:
        raise UseCaseError(
            "%s has several gates (%s); give one step id"
            % (target, ", ".join(g.id for g in gates))
        )
    return gates[0]


class HoldGateUseCase:
    def __init__(self, store):
        self._store = store
        self._hold = GateHold(store)

    def execute(self, input: HoldGateInput) -> HoldGateResponse:
        if self._store.type_of(input.target) == "item" and self._store.get_node(input.target).state == State.DONE:
            raise UseCaseError("%s is closed; there is nothing to hold" % input.target)
        step = resolve_gate_step(self._store, input.target, "hold")
        if step.state == State.DONE:
            raise UseCaseError("%s is closed; there is nothing to hold" % step.id)
        if step.state == State.RUNNING:
            raise UseCaseError("a worker is running %s - use `lc halt`" % step.id)
        if step.state != State.WAITING or step.role != "human":
            raise UseCaseError(
                "%s is not a waiting human gate - use `lc set` to change it" % step.id
            )
        if self._hold.is_held(step.id):
            raise UseCaseError("%s is already held - `lc release %s` first" % (step.id, step.id))
        self._hold.place(step.id, input.note)
        return HoldGateResponse(step=step.id, note=input.note)

from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.gate_hold import GateHold
from lightcycle.application.work.hold_gate import resolve_gate_step


@dataclass(frozen=True)
class ReleaseGateInput:
    target: str


@dataclass(frozen=True)
class ReleaseGateResponse:
    step: str


class ReleaseGateUseCase:
    def __init__(self, store):
        self._store = store
        self._hold = GateHold(store)

    def execute(self, input: ReleaseGateInput) -> ReleaseGateResponse:
        step = resolve_gate_step(self._store, input.target, "release")
        if not self._hold.is_held(step.id):
            raise UseCaseError("%s is not held" % step.id)
        self._hold.lift(step.id)
        return ReleaseGateResponse(step=step.id)

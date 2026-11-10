from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.gate_hold import GateHold


class RefuseGateHoldUseCase:
    def __init__(self, store):
        self._hold = GateHold(store)

    def execute(self, step_id):
        note = self._hold.note_of(step_id)
        if note is not None or self._hold.is_held(step_id):
            raise UseCaseError(
                "%s is held (%s) - lc release %s first, or lc close the item"
                % (step_id, note or "no note", step_id)
            )

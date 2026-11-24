from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.gate_hold import GateHold
from lightcycle.domain.work import State


class RefuseGateHoldUseCase:
    def __init__(self, store):
        self._hold = GateHold(store)
        self._store = store

    def _state_of(self, step_id):
        try:
            return self._store.get_node(step_id).state
        except KeyError:
            return None

    def execute(self, step_id, parking=False):
        if parking and self._state_of(step_id) != State.WAITING:
            return
        note = self._hold.note_of(step_id)
        if note is not None or self._hold.is_held(step_id):
            raise UseCaseError(
                "%s is held (%s) - lc release %s first, or lc close the item"
                % (step_id, note or "no note", step_id)
            )

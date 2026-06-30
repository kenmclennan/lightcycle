"""CompleteTask: close a task with a flow outcome and advance the chain."""
from the_grid.application.errors import UseCaseError
from the_grid.application.flow.advance_task import AdvanceTask
from the_grid.domain.contracts import StepContract


class CompleteTask:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow
        self._advance = AdvanceTask(store, flow)

    def execute(self, tid, outcome, note=None):
        t = self._store.get_task(tid)
        transition = self._flow.flow_next(t.step, outcome)
        if transition is None:
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.step, outcome))
        missing = StepContract.from_meta(self._flow.meta_for_step(t.step)).missing_outputs(
            self._store.present_types(t))
        if missing:
            raise UseCaseError(
                "cannot close %s: step '%s' must produce %s; none on the story. "
                "tg link the artifact first." % (tid, t.step, ", ".join(sorted(missing))))
        self._store.note(tid, "outcome: %s" % outcome)
        self._store.close(tid, outcome)
        new = self._advance.execute(tid, outcome)
        if note:
            target = new if new else tid
            self._store.note(target, transition.forward_note(note))
        return new

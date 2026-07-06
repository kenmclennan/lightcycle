from dataclasses import dataclass
from typing import Optional

from the_grid.application.errors import UseCaseError
from the_grid.application.flow.advance_task import AdvanceInput, AdvanceTaskUseCase
from the_grid.domain.contracts import StepContract


@dataclass(frozen=True)
class CompleteInput:
    task: str
    outcome: str
    note: Optional[str] = None


@dataclass(frozen=True)
class CompleteResponse:
    next_task: Optional[str]


class CompleteTaskUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow
        self._advance = AdvanceTaskUseCase(store, flow)

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_task(input.task)
        name = self._flow.workflow_for(t)
        transition = self._flow.flow_next(t.step, input.outcome, name)
        if transition is None and self._flow.outcomes_for(t.step, name):
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.step, input.outcome)
            )
        target = (
            StepContract.from_meta(self._flow.meta_for_step(transition.to_step, name))
            if transition
            else None
        )
        missing = StepContract.from_meta(self._flow.meta_for_step(t.step, name)).missing_outputs(
            self._store.present_types(t), target
        )
        if missing:
            raise UseCaseError(
                "cannot close %s: step '%s' must produce %s; none on the story. "
                "tg link the artifact first." % (input.task, t.step, ", ".join(sorted(missing)))
            )
        self._store.note(input.task, "outcome: %s" % input.outcome)
        self._store.close(input.task, input.outcome)
        new = self._advance.execute(AdvanceInput(task=input.task, outcome=input.outcome)).next_task
        if input.note:
            if transition:
                self._store.note(new if new else input.task, transition.forward_note(input.note))
            else:
                self._store.note(input.task, input.note)
        return CompleteResponse(next_task=new)

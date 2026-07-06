from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AdvanceInput:
    task: str
    outcome: str


@dataclass(frozen=True)
class AdvanceResponse:
    next_task: Optional[str]


class AdvanceTaskUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: AdvanceInput) -> AdvanceResponse:
        t = self._store.get_task(input.task)
        transition = self._flow.flow_next(t.step, input.outcome, self._flow.workflow_for(t))
        if transition is None:
            return AdvanceResponse(next_task=None)
        return AdvanceResponse(
            next_task=self._store.create_task(**transition.next_task_spec(t).as_kwargs())
        )

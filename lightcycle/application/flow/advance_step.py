from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AdvanceInput:
    step: str
    outcome: str


@dataclass(frozen=True)
class AdvanceResponse:
    next_step: Optional[str]


class AdvanceStepUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: AdvanceInput) -> AdvanceResponse:
        t = self._store.get_node(input.step)
        transition = self._flow.flow_next(
            t.step, input.outcome, self._flow.workflow_for(t), self._flow.project_for(t)
        )
        if transition is None:
            return AdvanceResponse(next_step=None)
        return AdvanceResponse(
            next_step=self._store.create_step(**transition.next_step_spec(t).as_kwargs())
        )

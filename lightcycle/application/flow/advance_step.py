from dataclasses import dataclass
from typing import Optional

from lightcycle.application.flow.next_step import NextStepResolver


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
        self._resolver = NextStepResolver(store, flow)

    def execute(self, input: AdvanceInput) -> AdvanceResponse:
        t = self._store.get_node(input.step)
        name = self._flow.workflow_for(t)
        project = self._flow.project_for(t)
        transition = self._resolver.resolve(t, input.outcome, name, project)
        if transition is None:
            return AdvanceResponse(next_step=None)
        return AdvanceResponse(next_step=self._resolver.create(t, transition))

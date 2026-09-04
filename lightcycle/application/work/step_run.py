from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.runs import run_id


@dataclass(frozen=True)
class StepRunInput:
    step: str


@dataclass(frozen=True)
class StepRunResponse:
    branch: Optional[str]
    pr: Optional[str]


class StepRunUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: StepRunInput) -> StepRunResponse:
        step = self._store.get_node(input.step)
        run = self._run_for(step)
        if run is None:
            return StepRunResponse(branch=None, pr=None)
        return StepRunResponse(branch=run.branch, pr=run.pr)

    def _run_for(self, step):
        if step.pass_id is None:
            return None
        phase = self._flow.phase_for(step)
        return self._store.get_run(run_id(step.pass_id, phase))

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StepRunInput:
    step: str


@dataclass(frozen=True)
class StepRunResponse:
    branch: Optional[str]
    pr: Optional[str]
    item: Optional[str] = None
    phase: Optional[str] = None
    pass_id: Optional[str] = None
    round: int = 1


class StepRunUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: StepRunInput) -> StepRunResponse:
        step = self._store.get_node(input.step)
        run = self._run_for(step)
        if run is None:
            return StepRunResponse(branch=None, pr=None)
        return StepRunResponse(
            branch=run.branch, pr=run.pr, item=run.item, phase=run.phase, pass_id=run.pass_id,
            round=run.round,
        )

    def _run_for(self, step):
        if step.pass_id is None:
            return None
        phase = self._flow.phase_for(step)
        runs = [r for r in self._store.runs_of(step.item, step.pass_id) if r.phase == phase]
        return runs[-1] if runs else None

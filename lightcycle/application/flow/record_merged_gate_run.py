from dataclasses import dataclass

from lightcycle.application.pool.pr_lookups import false_on_failure
from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.domain.runs import RunState
from lightcycle.domain.work.state import State


@dataclass(frozen=True)
class RecordMergedGateRunInput:
    step: str
    outcome: str


class RecordMergedGateRunUseCase:
    def __init__(self, store, github, flow):
        self._store = store
        self._github = github
        self._flow = flow

    def execute(self, input: RecordMergedGateRunInput) -> bool:
        step = self._store.get_node(input.step)
        if step.state == State.DONE:
            return False
        flow = self._flow.flow_for(step)
        step_def = flow.step_def(step.stage)
        if not step_def.pr_merge or step_def.pr_merge != input.outcome:
            return False
        name = self._flow.workflow_for(step)
        if self._flow.ends_pass(step.stage, input.outcome, name):
            return False
        run = self._store.current_run(step.item, step_def.phase)
        if run is None or run.pr is None or run.state != RunState.OPEN:
            return False
        if not self._pr_merged(run):
            return False
        self._store.close_run(run.id, RunState.MERGED)
        return True

    def _pr_merged(self, run):
        if run.stack:
            layers = read_stack(self._github, run.stack).layers
            return bool(layers) and layers[-1].state == "merged"
        return bool(false_on_failure(self._github.is_merged(run.pr)))

from dataclasses import dataclass

from lightcycle.application.work.step_context import StepContext
from lightcycle.application.work.step_detail import StepDetail
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.application.work.step_run import StepRunInput, StepRunUseCase
from lightcycle.domain.work.step_focus import (
    FocusFacts,
    StepFocus,
    resolve_focus,
)


@dataclass(frozen=True)
class ResolveStepFocusInput:
    step: str


@dataclass(frozen=True)
class ResolveStepFocusResponse:
    focus: StepFocus


class ResolveStepFocusUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: ResolveStepFocusInput) -> ResolveStepFocusResponse:
        node = self._store.get_node(input.step)
        if node.type == "item":
            return ResolveStepFocusResponse(focus=resolve_focus(FocusFacts(is_item=True)))
        run = StepRunUseCase(self._store, self._flow).execute(StepRunInput(step=node.id))
        step_inputs = StepInputs(self._store, self._flow)
        entries, presents = StepDetail(self._store, self._flow).resolve(
            node, step_inputs.read(node), step_inputs.entry_dicts_for_step(node), run=run)
        valued = {e.key: e.value for e in entries if e.value is not None}
        facts = FocusFacts(
            state=node.state,
            role=node.role or "human",
            presents_key=presents if presents in valued else None,
            first_value_key=next(iter(valued), None),
            has_log=node.log_path is not None,
            has_pr=bool(run.pr),
            has_reason=bool(node.park.reason),
            produced_outputs=self._produced_outputs(node, step_inputs),
            context_rows=len(StepContext(self._store, self._flow).read(node).rows),
            parked=bool(node.park.reason or node.park.needs),
        )
        return ResolveStepFocusResponse(focus=resolve_focus(facts))

    def _produced_outputs(self, node, step_inputs):
        return tuple(e["name"] for e in step_inputs.entry_dicts_for_step(node))

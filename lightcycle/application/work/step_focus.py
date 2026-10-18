from dataclasses import dataclass

from lightcycle.application.work.item_outputs import ItemOutputs
from lightcycle.application.work.step_detail import StepDetail
from lightcycle.application.work.step_inputs import StepInputs
from lightcycle.application.work.step_run import StepRunInput, StepRunUseCase
from lightcycle.domain.contracts import StepContract
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
        artifacts = self._store.item_artifacts(node.id)
        run = StepRunUseCase(self._store, self._flow).execute(StepRunInput(step=node.id))
        step_inputs = StepInputs(self._store, self._flow)
        entries, _presents = StepDetail(self._store, self._flow).resolve(
            node, step_inputs.read(node), step_inputs.entry_dicts_for_step(node), run=run)
        facts = FocusFacts(
            state=node.state,
            role=node.role or "human",
            presents=self._flow.flow_for(node).step_def(node.stage).presents,
            produced=self._produced(node),
            has_log=node.log_path is not None,
            artifact_types=self._artifact_types(node, artifacts),
            has_pr=bool(run.pr),
            bare_detail=all(e.value is None for e in entries),
            parked=bool(node.park.reason or node.park.needs),
        )
        return ResolveStepFocusResponse(focus=resolve_focus(facts))

    def _produced(self, node):
        try:
            meta = self._flow.meta_for_step(node.stage, self._flow.workflow_for(node))
        except ValueError:
            return ()
        return StepContract.from_meta(meta).produced_types()

    def _artifact_types(self, node, own):
        types = {a.type for a in own}
        types.update(ItemOutputs(self._store, self._flow).for_reader(node).types)
        return frozenset(types)

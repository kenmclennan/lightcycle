from dataclasses import dataclass

from lightcycle.application.work.step_run import StepRunInput, StepRunUseCase
from lightcycle.domain.contracts import StepContract
from lightcycle.domain.feedback import parse_reflections
from lightcycle.domain.work import latest_log_path
from lightcycle.domain.work.step_focus import (
    FocusFacts,
    StepFocus,
    detail_field_entries,
    is_bare_detail,
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
        reflections, _unreadable = parse_reflections(artifacts)
        session_id = next((a.value for a in artifacts if a.type == "session-id"), None)
        fields = detail_field_entries(
            node, run.pr, run.branch, None, session_id, [r.feedback for r in reflections])
        facts = FocusFacts(
            state=node.state,
            role=node.role or "human",
            presents=self._flow.flow_for(node).step_def(node.stage).presents,
            produced=self._produced(node),
            has_log=latest_log_path(artifacts) is not None,
            artifact_types=self._artifact_types(node, artifacts),
            has_pr=bool(run.pr),
            bare_detail=is_bare_detail(fields),
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
        types.update(a.type for a in self._store.item_artifacts(node.item))
        for sibling in self._store.children(node.item):
            types.update(a.type for a in self._store.item_artifacts(sibling.id))
        return frozenset(types)

from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.engine_steps import AUDIT_STEP, FINDINGS_STEP, RETRO_ORIGIN_LABEL
from lightcycle.application.flow.next_step import NextStepResolver
from lightcycle.application.flow.passes import PassBook
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.application.work.pending_reflections import pass_reflection_count
from lightcycle.domain.contracts import StepContract
from lightcycle.domain.work import NodeSpec
from lightcycle.domain.work.state import State

_AUTO_CLOSE_REASON = "auto-closed: all children done"


@dataclass(frozen=True)
class CompleteInput:
    step: str
    outcome: str
    note: Optional[str] = None


@dataclass(frozen=True)
class CompleteResponse:
    next_step: Optional[str]


class CompleteStepUseCase:
    def __init__(self, store, flow, worktrees=None, config=None):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees
        self._config = config
        self._resolver = NextStepResolver(store, flow)
        self._passes = PassBook(store, flow)

    def _expected_assignee(self):
        return self._config.spawn_id() if self._config else None

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_node(input.step)
        if t.state == State.DONE:
            return CompleteResponse(next_step=None)
        if self._is_retro_origin(t):
            if t.stage == AUDIT_STEP:
                return self._complete_engine_audit(t, input)
            if t.stage == FINDINGS_STEP:
                return self._complete_findings(t, input)
        return self._complete_workflow(t, input)

    def _is_retro_origin(self, t):
        return RETRO_ORIGIN_LABEL in self._store.labels_of(t.item)

    def _complete_workflow(self, t, input: CompleteInput) -> CompleteResponse:
        name = self._flow.workflow_for(t)
        transition = self._resolver.resolve(t, input.outcome, name)
        declared = self._flow.outcomes_for(t.stage, name)
        if transition is None and declared and input.outcome not in declared:
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.stage, input.outcome)
            )
        if transition is None and not self._flow.is_known_step(t.stage, name):
            decision = (
                "no transition for step=%s outcome=%s; the workflow does not define %s"
                % (t.stage, input.outcome, t.stage)
            )
            observation = (
                "step '%s' completed with outcome '%s', but workflow '%s' has no route "
                "defined for it" % (t.stage, input.outcome, name)
            )
            ParkStepUseCase(self._store).execute(
                ParkInput(step=input.step, observation=observation, decision=decision)
            )
            return CompleteResponse(next_step=None)
        target = (
            StepContract.from_meta(self._flow.meta_for_step(transition.to_stage, name))
            if transition
            else None
        )
        missing = StepContract.from_meta(
            self._flow.meta_for_step(t.stage, name)
        ).missing_outputs(
            self._store.present_types(t), target
        )
        if missing:
            raise UseCaseError(
                "cannot close %s: step '%s' must produce %s; none on the item. "
                "lc link the artifact first." % (input.step, t.stage, ", ".join(sorted(missing)))
            )
        spec = self._resolver.spec_for(t, transition)
        won, new = self._store.complete_step_atomic(
            input.step, input.outcome, self._expected_assignee(), spec)
        if not won:
            return CompleteResponse(next_step=None)
        if self._passes.ends_pass(t.stage, input.outcome, name):
            self._passes.close(t.item, self._worktrees)
        if new and transition:
            self._passes.enrol(t.item, new, transition.to_stage, name)
        self._store.note(input.step, "outcome: %s" % input.outcome)
        if input.note:
            if transition:
                self._store.note(new if new else input.step, transition.forward_note(input.note))
            else:
                self._store.note(input.step, input.note)
        self._cascade_close(t.item)
        return CompleteResponse(next_step=new)

    def _complete_engine_audit(self, t, input: CompleteInput) -> CompleteResponse:
        spec = None
        if input.outcome == "findings" and input.note:
            item_title = self._store.get_node(t.item).title
            spec = NodeSpec(
                title="%s: %s" % (FINDINGS_STEP, item_title), step=FINDINGS_STEP,
                role="human", parent=t.item)
        won, fid = self._store.complete_step_atomic(
            input.step, input.outcome, self._expected_assignee(), spec)
        if not won:
            return CompleteResponse(next_step=None)
        self._store.note(input.step, "outcome: %s" % input.outcome)
        self._mark_retroed()
        if fid is not None:
            self._store.note(fid, input.note)
        self._cascade_close(t.item)
        return CompleteResponse(next_step=None)

    def _complete_findings(self, t, input: CompleteInput) -> CompleteResponse:
        won, _ = self._store.complete_step_atomic(
            input.step, input.outcome, self._expected_assignee(), None)
        if not won:
            return CompleteResponse(next_step=None)
        self._store.note(input.step, "outcome: %s" % input.outcome)
        self._cascade_close(t.item)
        return CompleteResponse(next_step=None)

    def _mark_retroed(self):
        for item in self._store.closed_unretroed_items():
            if has_feedback(self._store, item):
                self._store.label_add(item.id, "retroed")
        for pass_record in self._store.closed_unretroed_passes():
            if pass_reflection_count(self._store, pass_record) > 0:
                self._store.label_add(pass_record.id, "retroed")

    def _cascade_close(self, node_id):
        if not node_id:
            return
        node = self._store.get_node(node_id)
        children = self._store.children(node_id)
        if not children or any(c.state != State.DONE for c in children):
            return
        if node.type != "item":
            return
        CloseItemUseCase(self._store, self._worktrees).execute(
            CloseItemInput(item=node_id, reason=_AUTO_CLOSE_REASON, disposition="completed")
        )

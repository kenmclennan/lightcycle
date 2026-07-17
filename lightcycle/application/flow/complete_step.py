from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.next_step import NextStepResolver
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.application.work.close_theme import CloseThemeInput, CloseThemeUseCase
from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.domain.audit import FINDINGS_STEP, StepKind
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
        self._completers = {
            StepKind.WORKFLOW: self._complete_workflow,
            StepKind.ENGINE_AUDIT: self._complete_engine_audit,
            StepKind.ENGINE_FINDINGS: self._complete_findings,
        }

    def _expected_assignee(self):
        return self._config.spawn_id() if self._config else None

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_node(input.step)
        if t.state == State.DONE:
            return CompleteResponse(next_step=None)
        return self._completers[StepKind.of(t)](t, input)

    def _complete_workflow(self, t, input: CompleteInput) -> CompleteResponse:
        name = self._flow.workflow_for(t)
        transition = self._resolver.resolve(t, input.outcome, name)
        declared = self._flow.outcomes_for(t.step, name)
        if transition is None and declared and input.outcome not in declared:
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.step, input.outcome)
            )
        if transition is None and not self._flow.is_known_step(t.step, name):
            self._store.route_to_human(
                input.step,
                "no transition for step=%s outcome=%s; the workflow does not define %s"
                % (t.step, input.outcome, t.step),
            )
            return CompleteResponse(next_step=None)
        target = (
            StepContract.from_meta(self._flow.meta_for_step(transition.to_step, name))
            if transition
            else None
        )
        missing = StepContract.from_meta(
            self._flow.meta_for_step(t.step, name)
        ).missing_outputs(
            self._store.present_types(t), target
        )
        if missing:
            raise UseCaseError(
                "cannot close %s: step '%s' must produce %s; none on the item. "
                "lc link the artifact first." % (input.step, t.step, ", ".join(sorted(missing)))
            )
        spec = transition.next_step_spec(t) if transition else None
        won, new = self._store.complete_step_atomic(
            input.step, input.outcome, self._expected_assignee(), spec)
        if not won:
            return CompleteResponse(next_step=None)
        self._store.note(input.step, "outcome: %s" % input.outcome)
        if input.note:
            if transition:
                self._store.note(new if new else input.step, transition.forward_note(input.note))
            else:
                self._store.note(input.step, input.note)
        self._cascade_close(t.parent)
        return CompleteResponse(next_step=new)

    def _complete_engine_audit(self, t, input: CompleteInput) -> CompleteResponse:
        spec = None
        if input.outcome == "findings" and input.note:
            spec = NodeSpec(
                title="review-findings: pending-feedback", step=FINDINGS_STEP,
                role="human", parent=t.parent, attention=True)
        won, fid = self._store.complete_step_atomic(
            input.step, input.outcome, self._expected_assignee(), spec)
        if not won:
            return CompleteResponse(next_step=None)
        self._store.note(input.step, "outcome: %s" % input.outcome)
        self._mark_retroed()
        if fid is not None:
            self._store.note(fid, input.note)
        self._cascade_close(t.parent)
        return CompleteResponse(next_step=None)

    def _complete_findings(self, t, input: CompleteInput) -> CompleteResponse:
        won, _ = self._store.complete_step_atomic(
            input.step, input.outcome, self._expected_assignee(), None)
        if not won:
            return CompleteResponse(next_step=None)
        self._store.note(input.step, "outcome: %s" % input.outcome)
        self._cascade_close(t.parent)
        return CompleteResponse(next_step=None)

    def _mark_retroed(self):
        for item in self._store.closed_unretroed_items():
            if has_feedback(self._store, item):
                self._store.label_add(item.id, "retroed")

    def _cascade_close(self, node_id):
        if not node_id:
            return
        node = self._store.get_node(node_id)
        children = self._store.children(node_id)
        if not children or any(c.state != State.DONE for c in children):
            return
        if node.type == "item":
            CloseItemUseCase(self._store, self._worktrees).execute(
                CloseItemInput(item=node_id, reason=_AUTO_CLOSE_REASON)
            )
        else:
            CloseThemeUseCase(self._store).execute(
                CloseThemeInput(theme=node_id, reason=_AUTO_CLOSE_REASON)
            )
        self._cascade_close(node.parent)

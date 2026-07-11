from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.application.work.close_theme import CloseThemeInput, CloseThemeUseCase
from lightcycle.domain.contracts import StepContract
from lightcycle.domain.flow.transition import Transition
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
    def __init__(self, store, flow, worktrees=None):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_node(input.step)
        name = self._flow.workflow_for(t)
        project = self._flow.project_for(t)
        transition = self._flow.flow_next(t.step, input.outcome, name, project)
        declared = self._flow.outcomes_for(t.step, name, project)
        if transition is None and declared and input.outcome not in declared:
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.step, input.outcome)
            )
        if transition is None and not self._flow.is_known_step(t.step, name, project):
            self._store.route_to_human(
                input.step,
                "no transition for step=%s outcome=%s; the workflow does not define %s"
                % (t.step, input.outcome, t.step),
            )
            return CompleteResponse(next_step=None)
        transition = self._capped(t, input.outcome, transition, name, project)
        target = (
            StepContract.from_meta(self._flow.meta_for_step(transition.to_step, name, project))
            if transition
            else None
        )
        missing = StepContract.from_meta(
            self._flow.meta_for_step(t.step, name, project)
        ).missing_outputs(
            self._store.present_types(t), target
        )
        if missing:
            raise UseCaseError(
                "cannot close %s: step '%s' must produce %s; none on the item. "
                "lc link the artifact first." % (input.step, t.step, ", ".join(sorted(missing)))
            )
        self._store.note(input.step, "outcome: %s" % input.outcome)
        self._store.close(input.step, input.outcome)
        new = (
            self._store.create_step(**transition.next_step_spec(t).as_kwargs())
            if transition
            else None
        )
        if input.note:
            if transition:
                self._store.note(new if new else input.step, transition.forward_note(input.note))
            else:
                self._store.note(input.step, input.note)
        self._cascade_close(t.parent)
        return CompleteResponse(next_step=new)

    def _capped(self, t, outcome, transition, name, project):
        if transition is None:
            return None
        cap_outcome = self._flow.ci_failed_cap_outcome(t.step, name, project)
        if cap_outcome is None or outcome != cap_outcome:
            return transition
        cap_n = self._flow.ci_failed_cap_n(t.step, name, project)
        cap_target = self._flow.ci_failed_cap_target(t.step, name, project)
        if cap_n is None or not cap_target:
            return transition
        prior = sum(
            1 for s in self._store.steps_at_step(t.step)
            if s.parent == t.parent and s.state == State.DONE and s.outcome == outcome
        )
        if prior < cap_n:
            return transition
        return Transition(
            from_step=t.step,
            outcome=outcome,
            to_step=cap_target,
            to_role=self._flow.owner_of(cap_target, name, project) or "human",
        )

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

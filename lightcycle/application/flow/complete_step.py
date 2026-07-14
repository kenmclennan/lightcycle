from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.next_step import NextStepResolver
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.application.work.close_theme import CloseThemeInput, CloseThemeUseCase
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.contracts import StepContract
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
        self._resolver = NextStepResolver(store, flow)

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_node(input.step)
        name = self._flow.workflow_for(t)
        project = self._flow.project_for(t)
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
        self._store.note(input.step, "outcome: %s" % input.outcome)
        self._store.close(input.step, input.outcome)
        if project and self._flow.is_retro_cadence_step(t.step, name):
            self._mark_retroed(project)
        new = self._resolver.create(t, transition) if transition else None
        if input.note:
            if transition:
                self._store.note(new if new else input.step, transition.forward_note(input.note))
            else:
                self._store.note(input.step, input.note)
        self._cascade_close(t.parent)
        return CompleteResponse(next_step=new)

    def _mark_retroed(self, project):
        for item in self._store.closed_unretroed_items():
            if project_of(self._store, item) == project:
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

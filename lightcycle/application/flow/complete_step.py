from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.advance_step import AdvanceInput, AdvanceStepUseCase
from lightcycle.application.work.close_item import CloseItemInput, CloseItemUseCase
from lightcycle.application.work.close_theme import CloseThemeInput, CloseThemeUseCase
from lightcycle.domain.contracts import StepContract
from lightcycle.domain.work.status import Status

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
        self._advance = AdvanceStepUseCase(store, flow)

    def execute(self, input: CompleteInput) -> CompleteResponse:
        t = self._store.get_node(input.step)
        name = self._flow.workflow_for(t)
        project = self._flow.project_for(t)
        transition = self._flow.flow_next(t.step, input.outcome, name, project)
        if transition is None and self._flow.outcomes_for(t.step, name, project):
            raise UseCaseError(
                "no transition for step=%s outcome=%s; not closing. "
                "Fix the flow or use a defined outcome." % (t.step, input.outcome)
            )
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
        new = self._advance.execute(AdvanceInput(step=input.step, outcome=input.outcome)).next_step
        if input.note:
            if transition:
                self._store.note(new if new else input.step, transition.forward_note(input.note))
            else:
                self._store.note(input.step, input.note)
        self._cascade_close(t.parent)
        return CompleteResponse(next_step=new)

    def _cascade_close(self, node_id):
        if not node_id:
            return
        node = self._store.get_node(node_id)
        children = self._store.children(node_id)
        if not children or any(c.status != Status.DONE for c in children):
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

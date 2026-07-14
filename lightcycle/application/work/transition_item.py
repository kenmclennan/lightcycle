from dataclasses import dataclass

from lightcycle.application.work.step_filing import file_step
from lightcycle.domain.work import State


@dataclass(frozen=True)
class TransitionItemInput:
    item: str
    outcome: str
    workflow: str
    step: str


@dataclass(frozen=True)
class TransitionItemResponse:
    item: str
    step: str


class TransitionItemUseCase:
    def __init__(self, store, flow, worktrees):
        self._store = store
        self._flow = flow
        self._worktrees = worktrees

    def execute(self, input: TransitionItemInput) -> TransitionItemResponse:
        for child in self._store.children(input.item):
            if child.state != State.DONE:
                self._store.close(child.id, input.outcome)
        old = self._store.get_node(input.item)
        new_workflow = self._flow.repin_name(old.workflow, input.workflow)
        self._worktrees.remove(input.item)
        self._store.edit_node(input.item, workflow=new_workflow)
        node = self._store.get_node(input.item)
        step = file_step(self._store, self._flow, input.item, node, new_workflow, input.step)
        return TransitionItemResponse(item=input.item, step=step)

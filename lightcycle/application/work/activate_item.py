from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.step_filing import file_step
from lightcycle.domain.work import State


@dataclass(frozen=True)
class ActivateItemInput:
    item: str
    workflow: Optional[str] = None
    theme: Optional[str] = None
    step: Optional[str] = None


@dataclass(frozen=True)
class ActivateItemResponse:
    step: str


class ActivateItemUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: ActivateItemInput) -> ActivateItemResponse:
        node = self._store.get_node(input.item)
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        if node.state != State.BACKLOGGED:
            raise UseCaseError("item '%s' is not a todo (state=%s)" % (input.item, node.state))
        item_id = input.item
        if input.theme is not None:
            item_id = self._store.edit_node(input.item, parent=input.theme)
            node = self._store.get_node(item_id)
        workflow = input.workflow or self._flow.workflow_for(node)
        project = self._flow.project_for(node)
        self._store.edit_node(item_id, workflow=input.workflow)
        step = file_step(
            self._store, self._flow, item_id, node, workflow, project, input.step
        )
        return ActivateItemResponse(step=step)

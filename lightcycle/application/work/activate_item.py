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
        selection = input.workflow
        if selection is None:
            selection = self._flow.inherited_selection(node)
        if selection is None:
            raise UseCaseError(
                "no workflow selected for '%s'; pass --workflow <origin>/<name> or set one on an "
                "ancestor theme" % input.item)
        pin = self._flow.resolve_selection(selection)
        self._store.edit_node(item_id, workflow=pin)
        step = file_step(self._store, self._flow, item_id, node, pin, input.step)
        return ActivateItemResponse(step=step)

from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.project_clone import ensure_project_cloned
from lightcycle.application.work.step_filing import check_step_filing, file_step
from lightcycle.domain.work import State


@dataclass(frozen=True)
class ActivateItemInput:
    item: str
    workflow: Optional[str] = None
    step: Optional[str] = None
    deps: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActivateItemResponse:
    step: str


class ActivateItemUseCase:
    def __init__(self, store, flow, git, config):
        self._store = store
        self._flow = flow
        self._git = git
        self._config = config

    def execute(self, input: ActivateItemInput) -> ActivateItemResponse:
        node = self._store.get_node(input.item)
        if node.type != "item":
            raise UseCaseError("'%s' is not an item (type=%s)" % (input.item, node.type))
        if node.state != State.BACKLOGGED:
            raise UseCaseError("item '%s' is not a todo (state=%s)" % (input.item, node.state))
        item_id = input.item
        selection = input.workflow
        if selection is None:
            selection = self._flow.inherited_selection(node)
        if selection is None:
            raise UseCaseError(
                "no workflow selected for '%s'; pass --workflow <origin>/<name>" % input.item)
        try:
            pin = self._flow.resolve_selection(selection)
            self._flow.load_graph(pin)
        except ValueError as e:
            raise UseCaseError(str(e))
        step_name, role = check_step_filing(self._store, self._flow, item_id, node, pin, input.step)
        repo = self._store.get_item(item_id).repo
        ensure_project_cloned(self._store, self._git, self._config, repo)
        self._store.edit_node(item_id, workflow=pin)
        step = file_step(
            self._store, self._flow, item_id, node, pin, step_name, role, deps=input.deps
        )
        return ActivateItemResponse(step=step)

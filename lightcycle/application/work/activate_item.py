from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class ActivateItemInput:
    item: str
    workflow: Optional[str] = None
    theme: Optional[str] = None


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
        if node.state != "todo":
            raise UseCaseError("item '%s' is not a todo (state=%s)" % (input.item, node.state))
        if input.theme is not None:
            self._store.edit_node(input.item, parent=input.theme)
            node = self._store.get_node(input.item)
        workflow = input.workflow or self._flow.workflow_for(node)
        project = self._flow.project_for(node)
        entry = self._flow.load_graph(workflow, project).entry
        flow = self._flow.load_flow(workflow, project)
        role = flow.owner_of(entry)
        if not role:
            raise UseCaseError(
                "entry step '%s' in workflow '%s' has no owner" % (entry, workflow)
            )
        self._store.edit_node(input.item, workflow=workflow, state="active")
        step = self._store.create_step(
            "%s: %s" % (entry, node.title), step=entry, role=role, parent=input.item
        )
        return ActivateItemResponse(step=step)

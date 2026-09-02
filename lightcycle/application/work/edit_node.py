from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError


@dataclass(frozen=True)
class EditNodeInput:
    step: str
    title: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    project: Optional[str] = None
    parent: Optional[str] = None
    workflow: Optional[str] = None


@dataclass(frozen=True)
class EditNodeResponse:
    id: str


class EditNodeUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: EditNodeInput) -> EditNodeResponse:
        if input.parent is not None and self._store.get_node(input.step).type == "item":
            raise UseCaseError(
                "'%s' is an item; items are top-level and cannot be reparented" % input.step)
        tid = self._store.edit_node(
            input.step,
            title=input.title,
            description=input.description,
            goal=input.goal,
            project=input.project,
            parent=input.parent,
            workflow=input.workflow,
        )
        return EditNodeResponse(id=tid)

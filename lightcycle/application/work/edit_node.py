from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EditNodeInput:
    step: str
    title: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    project: Optional[str] = None
    parent: Optional[str] = None


@dataclass(frozen=True)
class EditNodeResponse:
    id: str


class EditNodeUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: EditNodeInput) -> EditNodeResponse:
        tid = self._store.edit_node(
            input.step,
            title=input.title,
            description=input.description,
            goal=input.goal,
            project=input.project,
            parent=input.parent,
        )
        return EditNodeResponse(id=tid)

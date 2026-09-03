from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EditNodeInput:
    step: str
    title: Optional[str] = None
    description: Optional[str] = None
    project: Optional[str] = None
    workflow: Optional[str] = None


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
            project=input.project,
            workflow=input.workflow,
        )
        return EditNodeResponse(id=tid)

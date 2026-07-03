from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EditTaskInput:
    task: str
    title: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    project: Optional[str] = None
    parent: Optional[str] = None


@dataclass(frozen=True)
class EditTaskResponse:
    pass


class EditTaskUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: EditTaskInput) -> EditTaskResponse:
        self._store.edit_task(
            input.task,
            title=input.title,
            description=input.description,
            goal=input.goal,
            project=input.project,
            parent=input.parent,
        )
        return EditTaskResponse()

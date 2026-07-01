"""AddTask: create a standalone human task (no spec, no flow)."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AddTaskInput:
    title: str
    goal: Optional[str] = None
    project: Optional[str] = None


@dataclass(frozen=True)
class AddTaskResponse:
    task: str


class AddTaskUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self, input: AddTaskInput) -> AddTaskResponse:
        return AddTaskResponse(task=self._store.create_task(
            input.title, role="human", project=input.project, goal=input.goal))

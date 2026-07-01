"""ShowTask: one task or story as a view dict (artifacts + resume-state)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ShowTaskInput:
    task: str


@dataclass(frozen=True)
class ShowTaskResponse:
    view: dict


class ShowTaskUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self, input: ShowTaskInput) -> ShowTaskResponse:
        return ShowTaskResponse(view=self._store.task_view(input.task))

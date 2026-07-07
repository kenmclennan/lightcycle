from dataclasses import dataclass

from lightcycle.domain.work import TaskView


@dataclass(frozen=True)
class ShowTaskInput:
    task: str


@dataclass(frozen=True)
class ShowTaskResponse:
    view: TaskView


class ShowTaskUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: ShowTaskInput) -> ShowTaskResponse:
        return ShowTaskResponse(view=self._store.task_view(input.task))

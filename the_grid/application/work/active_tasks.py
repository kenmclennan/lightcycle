"""ActiveTasks: tasks a worker is running right now (in-progress)."""
from dataclasses import dataclass
from typing import List

from the_grid.domain.work import Task, TaskQueue


@dataclass(frozen=True)
class ActiveTasksResponse:
    tasks: List[Task]


class ActiveTasksUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self) -> ActiveTasksResponse:
        return ActiveTasksResponse(tasks=TaskQueue(self._store.all_tasks()).by_status("in-progress"))

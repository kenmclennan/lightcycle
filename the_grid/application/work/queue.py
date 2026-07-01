"""Queue: the next N ready or blocked agent tasks."""
from dataclasses import dataclass
from typing import List

from the_grid.domain.work import Task, TaskQueue


@dataclass(frozen=True)
class QueueInput:
    n: int = 10


@dataclass(frozen=True)
class QueueResponse:
    tasks: List[Task]


class QueueUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self, input: QueueInput) -> QueueResponse:
        queue = TaskQueue(self._store.all_tasks())
        return QueueResponse(tasks=(queue.by_status("ready") + queue.by_status("blocked"))[:input.n])

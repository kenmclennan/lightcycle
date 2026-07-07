from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import Task, TaskQueue


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
        ready_ids = {t.id for t in self._store.ready_tasks()}
        lanes = TaskQueue(self._store.all_tasks()).by_lane(ready_ids)
        return QueueResponse(tasks=(lanes["queue"] + lanes["blocked"])[: input.n])

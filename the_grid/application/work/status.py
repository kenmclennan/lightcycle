"""Status: all tasks bucketed into inbox / active / queue / blocked / done."""
from dataclasses import dataclass
from typing import Dict, List

from the_grid.domain.work import Task, TaskQueue


@dataclass(frozen=True)
class StatusResponse:
    buckets: Dict[str, List[Task]]


class StatusUseCase:

    def __init__(self, store):
        self._store = store

    def execute(self) -> StatusResponse:
        return StatusResponse(buckets=TaskQueue(self._store.all_tasks()).bucket())

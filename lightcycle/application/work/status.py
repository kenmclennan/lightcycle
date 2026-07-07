from dataclasses import dataclass
from typing import Dict, List

from lightcycle.domain.work import Task, TaskQueue


@dataclass(frozen=True)
class StatusResponse:
    lanes: Dict[str, List[Task]]


class StatusUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self) -> StatusResponse:
        ready_ids = {t.id for t in self._store.ready_tasks()}
        return StatusResponse(lanes=TaskQueue(self._store.all_tasks()).by_lane(ready_ids))

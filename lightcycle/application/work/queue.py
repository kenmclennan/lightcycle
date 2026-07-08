from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import Node, NodeQueue


@dataclass(frozen=True)
class QueueInput:
    n: int = 10


@dataclass(frozen=True)
class QueueResponse:
    steps: List[Node]


class QueueUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: QueueInput) -> QueueResponse:
        ready_ids = {t.id for t in self._store.ready_steps()}
        lanes = NodeQueue(self._store.all_steps()).by_lane(ready_ids)
        return QueueResponse(steps=(lanes["queue"] + lanes["blocked"])[: input.n])

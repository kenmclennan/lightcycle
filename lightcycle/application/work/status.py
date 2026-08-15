from dataclasses import dataclass
from typing import Dict, List

from lightcycle.application.work.watched_steps import watched_step_ids
from lightcycle.domain.work import Node, NodeQueue


@dataclass(frozen=True)
class StatusResponse:
    lanes: Dict[str, List[Node]]


class StatusUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self) -> StatusResponse:
        watched = watched_step_ids(self._store)
        steps = [t for t in self._store.all_steps() if t.id not in watched]
        return StatusResponse(lanes=NodeQueue(steps).by_lane())

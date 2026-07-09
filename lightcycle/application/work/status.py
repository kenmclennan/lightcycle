from dataclasses import dataclass
from typing import Dict, List

from lightcycle.domain.work import Node, NodeQueue


@dataclass(frozen=True)
class StatusResponse:
    lanes: Dict[str, List[Node]]


class StatusUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self) -> StatusResponse:
        return StatusResponse(lanes=NodeQueue(self._store.all_steps()).by_lane())

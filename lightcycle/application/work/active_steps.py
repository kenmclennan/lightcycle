from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import Node, NodeQueue, State


@dataclass(frozen=True)
class ActiveStepsResponse:
    steps: List[Node]


class ActiveStepsUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self) -> ActiveStepsResponse:
        return ActiveStepsResponse(
            steps=NodeQueue(self._store.all_steps()).by_state(State.IN_PROGRESS)
        )

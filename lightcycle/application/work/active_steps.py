from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import NodeQueue, State, Step


@dataclass(frozen=True)
class ActiveStepsResponse:
    steps: List[Step]


class ActiveStepsUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self) -> ActiveStepsResponse:
        return ActiveStepsResponse(
            steps=NodeQueue(self._store.all_steps()).by_state(State.IN_PROGRESS)
        )

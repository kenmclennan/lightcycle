from dataclasses import dataclass
from typing import List

from lightcycle.domain.flow import planned_path
from lightcycle.domain.work import ProjectedStep, State


@dataclass(frozen=True)
class PlannedStepsInput:
    item_id: str


class PlannedStepsUseCase:
    def __init__(self, store, flow_service):
        self._store = store
        self._flow_service = flow_service

    def execute(self, input: PlannedStepsInput) -> List[ProjectedStep]:
        current = next(
            (
                c for c in self._store.children(input.item_id)
                if c.type == "step" and c.state != State.DONE
            ),
            None,
        )
        if current is None:
            return []
        flow = self._flow_service.flow_for(current)
        path = planned_path(flow, current.step)
        already_filed = len(self._store.children(input.item_id))
        return [
            ProjectedStep(
                id="%s.%d" % (input.item_id, already_filed + i + 1),
                step=stage,
                role=role,
            )
            for i, (stage, role) in enumerate(path)
        ]

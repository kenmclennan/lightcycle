from dataclasses import dataclass
from typing import List, Optional

from the_grid.application.work.human_task_row import HumanTaskRow
from the_grid.domain.work import TaskQueue


@dataclass(frozen=True)
class BacklogInput:
    n: Optional[int] = None


@dataclass(frozen=True)
class BacklogResponse:
    rows: List[HumanTaskRow]


class BacklogUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: BacklogInput) -> BacklogResponse:
        rows = TaskQueue(self._store.all_tasks()).for_human(
            self._flow.load_flow(), {"todo"}, input.n
        )
        return BacklogResponse(
            rows=[HumanTaskRow(kind=k, outcomes=o, task=t) for (k, o), t in rows]
        )

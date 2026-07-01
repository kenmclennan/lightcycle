"""Mine (deprecated): all human tasks combined, ordered blocked > action > todo."""
from dataclasses import dataclass
from typing import List

from the_grid.application.work.human_task_row import HumanTaskRow
from the_grid.domain.work import TaskQueue

_MINE_ORDER = {"blocked": 0, "action": 1, "todo": 2}


@dataclass(frozen=True)
class MineResponse:
    rows: List[HumanTaskRow]


class MineUseCase:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self) -> MineResponse:
        rows = TaskQueue(self._store.all_tasks()).for_human(
            self._flow.load_flow(), {"todo", "action", "blocked"})
        rows.sort(key=lambda r: (_MINE_ORDER.get(r[0][0], 9), r[1].id))
        return MineResponse(rows=[HumanTaskRow(kind=k, outcomes=o, task=t) for (k, o), t in rows])

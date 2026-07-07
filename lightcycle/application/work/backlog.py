from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.domain.work import NodeQueue


@dataclass(frozen=True)
class BacklogInput:
    n: Optional[int] = None


@dataclass(frozen=True)
class BacklogResponse:
    rows: List[HumanNodeRow]


class BacklogUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: BacklogInput) -> BacklogResponse:
        rows = NodeQueue(self._store.all_nodes()).for_human(
            self._flow.load_flow(), {"todo"}, input.n
        )
        return BacklogResponse(
            rows=[HumanNodeRow(kind=k, outcomes=o, step=t) for (k, o), t in rows]
        )

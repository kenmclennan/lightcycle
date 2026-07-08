from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow


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
        items = [n for n in self._store.all_nodes() if n.type == "item" and n.state == "todo"]
        items.sort(key=lambda t: t.id)
        if input.n is not None:
            items = items[:input.n]
        return BacklogResponse(
            rows=[HumanNodeRow(kind="todo", outcomes=[], step=t) for t in items]
        )

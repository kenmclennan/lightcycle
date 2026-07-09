from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.domain.work import NodeQueue


@dataclass(frozen=True)
class InboxInput:
    n: Optional[int] = None


@dataclass(frozen=True)
class InboxResponse:
    rows: List[HumanNodeRow]


class InboxUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: InboxInput) -> InboxResponse:
        rows = NodeQueue(self._store.all_steps()).for_human(
            self._flow.load_flow(), {"action", "blocked", "triage"}, input.n)
        return InboxResponse(
            rows=[HumanNodeRow(kind=k, outcomes=o, step=t) for (k, o), t in rows],
        )

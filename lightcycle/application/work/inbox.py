from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.domain.work import Item, NodeQueue


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
        return InboxResponse(rows=[self._row(k, o, t) for (k, o), t in rows])

    def _row(self, kind, outcomes, t):
        item = self._item(t.parent) if t.parent else None
        return HumanNodeRow(
            kind=kind, outcomes=outcomes, step=t,
            project=item.repo() if item else None,
            pr=item.artifact_of("pr") if item else None,
        )

    def _item(self, item_id):
        return Item(item_id, tuple(self._store.item_artifacts(item_id)))

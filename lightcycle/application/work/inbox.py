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
        resolver = self._resolver()
        watched = self._watched_step_ids()
        steps = [t for t in self._store.all_steps() if t.id not in watched]
        rows = NodeQueue(steps).for_human(
            resolver, {"action", "blocked", "triage"}, input.n)
        return InboxResponse(rows=[self._row(k, o, t, resolver) for (k, o), t in rows])

    def _watched_step_ids(self):
        watched = set()
        for n in self._store.all_nodes():
            if n.type != "step":
                continue
            for a in self._store.item_artifacts(n.id):
                if a.type == "watched-step":
                    watched.add(a.value)
        return watched

    def _resolver(self):
        cache = {}

        def resolve(t):
            pin = self._flow.workflow_for(t)
            if pin not in cache:
                cache[pin] = self._flow.load_flow(pin)
            return cache[pin]

        return resolve

    def _row(self, kind, outcomes, t, resolver):
        item = self._item(t.parent) if t.parent else None
        return HumanNodeRow(
            kind=kind, outcomes=outcomes, step=t,
            project=item.repo() if item else None,
            pr=item.artifact_of("pr", label=resolver(t).phase_of(t.step)) if item else None,
        )

    def _item(self, item_id):
        return Item(item_id, tuple(self._store.item_artifacts(item_id)))

from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.application.work.watched_steps import watched_step_ids
from lightcycle.domain.flow import Flow
from lightcycle.domain.work import NodeQueue
from lightcycle.ports.store import NodeNotFoundError

_NO_FLOW = Flow({})


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
        watched = watched_step_ids(self._store)
        steps = [t for t in self._store.all_steps() if t.id not in watched]
        rows = NodeQueue(steps).for_human(
            resolver, {"action", "blocked"}, input.n)
        return InboxResponse(rows=[self._row(k, o, t, resolver) for (k, o), t in rows])

    def _resolver(self):
        def resolve(t):
            selection = self._flow.workflow_for(t)
            return self._flow.flow_for(t) if selection is not None else _NO_FLOW

        return resolve

    def _row(self, kind, outcomes, t, resolver):
        item = self._item(t.item) if t.item else None
        return HumanNodeRow(
            kind=kind, outcomes=outcomes, step=t,
            project=item.repo if item else None,
            description=item.description if item else None,
            artifacts=item.artifacts if item else (),
            pr=self._pr_for(t, resolver),
        )

    def _pr_for(self, t, resolver):
        if not t.item:
            return None
        run = self._store.current_run(t.item, resolver(t).step_def(t.stage).phase)
        return run.pr if run else None

    def _item(self, item_id):
        try:
            return self._store.get_item(item_id)
        except NodeNotFoundError:
            return None

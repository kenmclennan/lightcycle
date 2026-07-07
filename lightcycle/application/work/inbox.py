import datetime
from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.domain.work import NodeQueue
from lightcycle.domain.work.status import Status

_QUIESCENCE_SECONDS = 3600


@dataclass(frozen=True)
class InboxInput:
    now: float
    n: Optional[int] = None


@dataclass(frozen=True)
class CandidateEpic:
    id: str
    title: str
    closed_item_count: int


@dataclass(frozen=True)
class InboxResponse:
    rows: List[HumanNodeRow]
    candidate_epics: List[CandidateEpic] = field(default_factory=list)


class InboxUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: InboxInput) -> InboxResponse:
        rows = NodeQueue(self._store.all_nodes()).for_human(
            self._flow.load_flow(), {"action", "blocked", "triage"}, input.n)
        return InboxResponse(
            rows=[HumanNodeRow(kind=k, outcomes=o, step=t) for (k, o), t in rows],
            candidate_epics=self._candidate_epics(input.now),
        )

    def _candidate_epics(self, now: float) -> List[CandidateEpic]:
        candidates = []
        for t in self._store.all_nodes():
            if t.type != "theme" or t.status == Status.DONE:
                continue
            children = self._store.children(t.id)
            items = [c for c in children if c.type == "item"]
            if not items or any(c.status != Status.DONE for c in items):
                continue
            if self._recently_settled(items, now):
                continue
            candidates.append(
                CandidateEpic(id=t.id, title=t.title, closed_item_count=len(items))
            )
        return candidates

    @staticmethod
    def _recently_settled(items, now) -> bool:
        closures = [s.closed_at for s in items if s.closed_at]
        if not closures:
            return False
        latest = max(_epoch(c) for c in closures)
        return now - latest < _QUIESCENCE_SECONDS


def _epoch(closed_at: str) -> float:
    return datetime.datetime.fromisoformat(closed_at.replace("Z", "+00:00")).timestamp()

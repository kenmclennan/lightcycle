"""Inbox: what needs a human now - human-owned steps and agent blocks."""
from dataclasses import dataclass
from typing import List, Optional

from the_grid.application.work.human_task_row import HumanTaskRow
from the_grid.domain.work import TaskQueue


@dataclass(frozen=True)
class InboxInput:
    n: Optional[int] = None


@dataclass(frozen=True)
class InboxResponse:
    rows: List[HumanTaskRow]


class InboxUseCase:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, input: InboxInput) -> InboxResponse:
        rows = TaskQueue(self._store.all_tasks()).for_human(
            self._flow.load_flow(), {"action", "blocked"}, input.n)
        return InboxResponse(rows=[HumanTaskRow(kind=k, outcomes=o, task=t) for (k, o), t in rows])

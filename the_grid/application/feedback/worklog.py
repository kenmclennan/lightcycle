import datetime
from dataclasses import dataclass
from typing import List, Optional

from the_grid.domain import feedback as cfeedback


@dataclass(frozen=True)
class WorklogInput:
    period_args: List[str]
    today: datetime.date
    tz: datetime.tzinfo


@dataclass(frozen=True)
class WorklogEntry:
    id: str
    title: str
    outcome: Optional[str]
    pr: Optional[str]


@dataclass(frozen=True)
class WorklogResponse:
    entries: List[WorklogEntry]


class WorklogUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: WorklogInput) -> WorklogResponse:
        period = cfeedback.Period.resolve(input.period_args, input.today)
        rows = cfeedback.Worklog(self._store.closed_stories()).entries(period, input.tz)
        return WorklogResponse(
            entries=[
                WorklogEntry(id=r["id"], title=r["title"], outcome=r["outcome"], pr=r["pr"])
                for r in rows
            ]
        )

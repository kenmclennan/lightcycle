import datetime
from dataclasses import dataclass
from typing import List

from lightcycle.domain import feedback as cfeedback
from lightcycle.domain.feedback import WorklogEntry


@dataclass(frozen=True)
class WorklogInput:
    period_args: List[str]
    today: datetime.date
    tz: datetime.tzinfo


@dataclass(frozen=True)
class WorklogResponse:
    entries: List[WorklogEntry]


class WorklogUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: WorklogInput) -> WorklogResponse:
        period = cfeedback.Period.resolve(input.period_args, input.today)
        entries = cfeedback.Worklog(self._store.closed_items()).entries(period, input.tz)
        return WorklogResponse(entries=list(entries))

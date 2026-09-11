from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.work.timestamp import parse_timestamp


@dataclass(frozen=True)
class WorklogEntry:
    id: str
    title: str
    outcome: Optional[str]
    pr: Optional[str]


class Worklog:
    def __init__(self, items):
        self._items = items

    def entries(self, period, tz):
        result = []
        for item in self._items:
            if not item.closed_at:
                continue
            if not period.contains(self._closed_date(item.closed_at, tz)):
                continue
            result.append(
                WorklogEntry(
                    id=item.id, title=item.title, outcome=item.outcome,
                    pr=item.artifact_of("pr"),
                )
            )
        return result

    @staticmethod
    def _closed_date(closed_at, tz):
        return parse_timestamp(closed_at).astimezone(tz).date()

import datetime
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.work import automation
from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.application.work.item_filter import project_matches, text_matches
from lightcycle.application.work.item_partition import is_closed_item
from lightcycle.application.work.project_counts import ProjectCount, project_counts
from lightcycle.application.work.project_of import project_of, repo_of
from lightcycle.domain.work import node_id_key, parse_timestamp

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


@dataclass(frozen=True)
class DoneInput:
    project: Optional[str] = None
    text: Optional[str] = None
    day: Optional[datetime.date] = None


@dataclass(frozen=True)
class DoneResponse:
    rows: List[HumanNodeRow]


@dataclass(frozen=True)
class DoneCountsResponse:
    projects: List[ProjectCount]
    unscoped: int
    total: int


@dataclass(frozen=True)
class DayCount:
    day: datetime.date
    count: int


def _day_matches(item, day):
    if day is None:
        return True
    parsed = parse_timestamp(item.closed_at)
    return parsed is not None and parsed.date() == day


class DoneUseCase:
    def __init__(self, store):
        self._store = store
        self._closed_items_cache = None

    def execute(self, input: DoneInput) -> DoneResponse:
        items = self._closed_items()
        items = [t for t in items if project_matches(t, input.project)]
        items = [t for t in items if text_matches(t, input.text)]
        items = [t for t in items if _day_matches(t, input.day)]
        items.sort(
            key=lambda t: (parse_timestamp(t.closed_at) or _MIN_TIMESTAMP, node_id_key(t.id)),
            reverse=True,
        )
        rows = [
            HumanNodeRow(
                kind="done", outcomes=[], step=t,
                project=project_of(self._store, t),
                repo=repo_of(self._store, t),
                description=t.description, artifacts=t.artifacts,
                title=t.title,
            )
            for t in items
        ]
        return DoneResponse(rows=rows)

    def counts(self) -> DoneCountsResponse:
        items = self._closed_items()
        projects, unscoped = project_counts(self._store, items)
        return DoneCountsResponse(projects=projects, unscoped=unscoped, total=len(items))

    def day_counts(self) -> List[DayCount]:
        items = self._closed_items()
        buckets = {}
        for t in items:
            parsed = parse_timestamp(t.closed_at)
            if parsed is None:
                continue
            buckets[parsed.date()] = buckets.get(parsed.date(), 0) + 1
        return sorted(
            (DayCount(day=day, count=count) for day, count in buckets.items()),
            key=lambda dc: dc.day, reverse=True,
        )

    def _closed_items(self):
        if self._closed_items_cache is None:
            self._closed_items_cache = [
                n for n in self._store.all_items_including_done()
                if is_closed_item(n) and not automation.is_automation_item(self._store, n)
            ]
        return self._closed_items_cache

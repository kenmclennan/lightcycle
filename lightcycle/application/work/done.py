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

CATEGORY_ALL = "all"
CATEGORY_NO_AUTOMATION = "no-automation"
CATEGORY_AUTOMATION = "automation"


@dataclass(frozen=True)
class DoneInput:
    project: Optional[str] = None
    text: Optional[str] = None
    day: Optional[datetime.date] = None
    category: str = CATEGORY_NO_AUTOMATION


@dataclass(frozen=True)
class DoneResponse:
    rows: List[HumanNodeRow]


@dataclass(frozen=True)
class DoneCountsResponse:
    projects: List[ProjectCount]
    unscoped: int
    total: int
    all_count: int = 0
    no_automation_count: int = 0
    automation_count: int = 0


@dataclass(frozen=True)
class DayCount:
    day: datetime.date
    count: int


def _category_matches(is_automation, category):
    if category == CATEGORY_ALL:
        return True
    if category == CATEGORY_AUTOMATION:
        return is_automation
    return not is_automation


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
        items = self._items_in(input.category)
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

    def counts(self, category: str = CATEGORY_NO_AUTOMATION) -> DoneCountsResponse:
        entries = self._closed_entries()
        without = [n for n, auto in entries if not auto]
        projects, unscoped = project_counts(self._store, without)
        return DoneCountsResponse(
            projects=projects, unscoped=unscoped,
            total=len(self._items_in(category)),
            all_count=len(entries),
            no_automation_count=len(without),
            automation_count=len(entries) - len(without),
        )

    def day_counts(
        self, project: Optional[str] = None, category: str = CATEGORY_NO_AUTOMATION,
    ) -> List[DayCount]:
        buckets = {}
        for t in self._items_in(category):
            if not project_matches(t, project):
                continue
            parsed = parse_timestamp(t.closed_at)
            if parsed is None:
                continue
            buckets[parsed.date()] = buckets.get(parsed.date(), 0) + 1
        return sorted(
            (DayCount(day=day, count=count) for day, count in buckets.items()),
            key=lambda dc: dc.day, reverse=True,
        )

    def _items_in(self, category):
        return [n for n, auto in self._closed_entries() if _category_matches(auto, category)]

    def _closed_entries(self):
        if self._closed_items_cache is None:
            self._closed_items_cache = [
                (n, automation.is_automation_item(self._store, n))
                for n in self._store.all_items_including_done()
                if is_closed_item(n)
            ]
        return self._closed_items_cache

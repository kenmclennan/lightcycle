import datetime
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from lightcycle.application.work.automation import is_automation_item
from lightcycle.application.work.item_partition import is_backlogged_item, is_closed_item
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import ItemCost, ProjectIdentity, item_cost, parse_timestamp
from lightcycle.domain.work.summary_split import split_summary


@dataclass(frozen=True)
class ReportInput:
    day: datetime.date


@dataclass(frozen=True)
class ProjectReport:
    project: Optional[str]
    completed: int
    abandoned: int
    spend: ItemCost
    delivered: Tuple[str, ...]
    fixed: Tuple[str, ...]
    improved: Tuple[str, ...]


@dataclass(frozen=True)
class ReportResponse:
    day: datetime.date
    completed: int
    abandoned: int
    spend: ItemCost
    automation_count: int
    automation_spend: ItemCost
    cache_hit_rate: Optional[float]
    backlog_start: int
    backlog_close: int
    backlog_delta: int
    summary: Optional[str]
    projects: Tuple[ProjectReport, ...]
    summary_unmatched: Optional[str]


def _earliest_step_created_by_item(steps):
    earliest = {}
    for s in steps:
        ts = parse_timestamp(s.created_at)
        if ts is None:
            continue
        if s.item not in earliest or ts < earliest[s.item]:
            earliest[s.item] = ts
    return earliest


def _backlog_size_asof(store, items, earliest_step_by_item, day_start):
    n = 0
    for item in items:
        created = parse_timestamp(item.created_at)
        if created is None or created >= day_start:
            continue
        closed = parse_timestamp(item.closed_at)
        if closed is not None and closed <= day_start:
            continue
        first_step = earliest_step_by_item.get(item.id)
        if first_step is not None and first_step < day_start and not is_backlogged_item(store, item):
            continue
        n += 1
    return n


def _local_midnight(day):
    return datetime.datetime.combine(day, datetime.time()).astimezone()


def _closed_on(item, day):
    parsed = parse_timestamp(item.closed_at)
    return parsed is not None and parsed.date() == day


def _backlog_start_and_close(store, day, steps=None, items=None):
    items = store.all_items_including_done() if items is None else items
    earliest = _earliest_step_created_by_item(store.all_steps_including_done() if steps is None else steps)
    start = _backlog_size_asof(store, items, earliest, _local_midnight(day))
    close = _backlog_size_asof(store, items, earliest, _local_midnight(day + datetime.timedelta(days=1)))
    return start, close


def _project_key(store, item):
    raw = project_of(store, item)
    return ProjectIdentity.short_name(raw) if raw else None


def _project_label(project):
    return project if project is not None else "No project"


def _project_reports(store, items, day, sections):
    groups: Dict[Optional[str], list] = {}
    for item in items:
        groups.setdefault(_project_key(store, item), []).append(item)
    reports = []
    for project, group in groups.items():
        lists = sections.get(project, {})
        reports.append(ProjectReport(
            project=project,
            completed=sum(1 for i in group if i.disposition == "completed"),
            abandoned=sum(1 for i in group if i.disposition in ("abandoned", "aborted")),
            spend=item_cost([s for i in group for s in store.children(i.id)]),
            delivered=tuple(lists.get("Delivered", ())),
            fixed=tuple(lists.get("Fixed", ())),
            improved=tuple(lists.get("Improved", ())),
        ))
    reports.sort(key=lambda r: (-(r.completed + r.abandoned), _project_label(r.project)))
    return tuple(reports)


class ReportUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: ReportInput) -> ReportResponse:
        all_items = self._store.all_items_including_done()
        closed_on_day = [i for i in all_items if is_closed_item(i) and _closed_on(i, input.day)]
        automation_items = [i for i in closed_on_day if is_automation_item(self._store, i)]
        automation_ids = {i.id for i in automation_items}
        items = [i for i in closed_on_day if i.id not in automation_ids]
        completed = sum(1 for i in items if i.disposition == "completed")
        abandoned = sum(1 for i in items if i.disposition in ("abandoned", "aborted"))
        automation_steps = [s for i in automation_items for s in self._store.children(i.id)]
        automation_spend = item_cost(automation_steps)
        all_children = [s for i in items for s in self._store.children(i.id)]
        spend = item_cost(all_children)
        day_cache_hit_rate = item_cost(all_children + automation_steps).cache_hit_rate
        all_steps = self._store.all_steps_including_done()
        backlog_start, backlog_close = _backlog_start_and_close(self._store, input.day, all_steps, all_items)
        row = self._store.day_summary(input.day)
        summary = row.summary if row else None
        project_by_item_id = {i.id: _project_key(self._store, i) for i in items}
        if summary:
            sections, unmatched = split_summary(summary, project_by_item_id)
        else:
            sections, unmatched = {}, None
        projects = _project_reports(self._store, items, input.day, sections)
        return ReportResponse(
            day=input.day, completed=completed, abandoned=abandoned, spend=spend,
            automation_count=len(automation_items), automation_spend=automation_spend,
            cache_hit_rate=day_cache_hit_rate,
            backlog_start=backlog_start, backlog_close=backlog_close,
            backlog_delta=backlog_close - backlog_start,
            summary=summary, projects=projects, summary_unmatched=unmatched,
        )

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from lightcycle.application.work.automation import is_automation_item
from lightcycle.application.work.item_partition import is_backlogged_item, is_closed_item
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import ItemCost, ProjectIdentity, SlowStep, item_cost, parse_timestamp, slow_steps
from lightcycle.domain.work.summary_split import split_summary
from lightcycle.ports.store import NodeNotFoundError


@dataclass(frozen=True)
class ReportInput:
    day: datetime.date


@dataclass(frozen=True)
class ProjectReport:
    project: Optional[str]
    completed: int
    abandoned: int
    spend: ItemCost
    escalations: int
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
    escalations: int
    slow_steps: List[SlowStep]
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


def _escalations_on(store, day):
    count = 0
    for node_id, ts in store.waiting_history():
        parsed = parse_timestamp(ts)
        if parsed is not None and parsed.date() == day:
            count += 1
    return count


def _project_key(store, item):
    raw = project_of(store, item)
    return ProjectIdentity.short_name(raw) if raw else None


def _escalations_by_item(store, day):
    counts: Dict[str, int] = {}
    for node_id, ts in store.waiting_history():
        parsed = parse_timestamp(ts)
        if parsed is None or parsed.date() != day:
            continue
        try:
            node = store.get_node(node_id)
        except NodeNotFoundError:
            continue
        owner = getattr(node, "item", None) or node.id
        counts[owner] = counts.get(owner, 0) + 1
    return counts


def _project_label(project):
    return project if project is not None else "No project"


def _project_reports(store, items, day, sections):
    groups: Dict[Optional[str], list] = {}
    for item in items:
        groups.setdefault(_project_key(store, item), []).append(item)
    escalations = _escalations_by_item(store, day)
    reports = []
    for project, group in groups.items():
        lists = sections.get(project, {})
        reports.append(ProjectReport(
            project=project,
            completed=sum(1 for i in group if i.disposition == "completed"),
            abandoned=sum(1 for i in group if i.disposition in ("abandoned", "aborted")),
            spend=item_cost([s for i in group for s in store.children(i.id)]),
            escalations=sum(escalations.get(i.id, 0) for i in group),
            delivered=tuple(lists.get("Delivered", ())),
            fixed=tuple(lists.get("Fixed", ())),
            improved=tuple(lists.get("Improved", ())),
        ))
    reports.sort(key=lambda r: (-(r.completed + r.abandoned), _project_label(r.project)))
    return tuple(reports)


def _slow_steps_on(steps, day):
    found = []
    for slow in slow_steps(steps):
        closed = parse_timestamp(slow.step.closed_at)
        if closed is not None and closed.date() == day:
            found.append(slow)
    return found


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
        automation_spend = item_cost([s for i in automation_items for s in self._store.children(i.id)])
        all_children = [s for i in items for s in self._store.children(i.id)]
        spend = item_cost(all_children)
        escalations = _escalations_on(self._store, input.day)
        all_steps = self._store.all_steps_including_done()
        slow = _slow_steps_on(all_steps, input.day)
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
            escalations=escalations, slow_steps=slow,
            backlog_start=backlog_start, backlog_close=backlog_close,
            backlog_delta=backlog_close - backlog_start,
            summary=summary, projects=projects, summary_unmatched=unmatched,
        )

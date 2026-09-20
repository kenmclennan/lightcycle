import datetime
from dataclasses import dataclass
from typing import Optional

from lightcycle.application.work.automation import AutomationInput, AutomationUseCase
from lightcycle.application.work.done import DoneInput, DoneUseCase
from lightcycle.domain.work import ItemCost, item_cost, parse_timestamp


@dataclass(frozen=True)
class ReportInput:
    day: datetime.date


@dataclass(frozen=True)
class ReportResponse:
    day: datetime.date
    completed: int
    abandoned: int
    spend: ItemCost
    automation_count: int
    automation_spend: ItemCost
    escalations: int
    backlog_start: int
    backlog_close: int
    backlog_delta: int
    summary: Optional[str]


def _earliest_step_created_by_item(store):
    earliest = {}
    for s in store.all_steps_including_done():
        ts = parse_timestamp(s.created_at)
        if ts is None:
            continue
        if s.item not in earliest or ts < earliest[s.item]:
            earliest[s.item] = ts
    return earliest


def _backlog_size_asof(items, earliest_step_by_item, day_start):
    n = 0
    for item in items:
        created = parse_timestamp(item.created_at)
        if created is None or created >= day_start:
            continue
        closed = parse_timestamp(item.closed_at)
        if closed is not None and closed <= day_start:
            continue
        first_step = earliest_step_by_item.get(item.id)
        if first_step is not None and first_step < day_start:
            continue
        n += 1
    return n


def _local_midnight(day):
    return datetime.datetime.combine(day, datetime.time()).astimezone()


def _backlog_start_and_close(store, day):
    items = store.all_items_including_done()
    earliest = _earliest_step_created_by_item(store)
    start = _backlog_size_asof(items, earliest, _local_midnight(day))
    close = _backlog_size_asof(items, earliest, _local_midnight(day + datetime.timedelta(days=1)))
    return start, close


def _escalations_on(store, day):
    count = 0
    for node_id, ts in store.waiting_history():
        parsed = parse_timestamp(ts)
        if parsed is not None and parsed.date() == day:
            count += 1
    return count


class ReportUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: ReportInput) -> ReportResponse:
        done_uc = DoneUseCase(self._store)
        closed_today = done_uc.execute(DoneInput(day=input.day)).rows
        items = [r.step for r in closed_today]
        completed = sum(1 for i in items if i.disposition == "completed")
        abandoned = sum(1 for i in items if i.disposition in ("abandoned", "aborted"))
        automation = AutomationUseCase(self._store).execute(AutomationInput(day=input.day)).total
        all_children = [s for i in items for s in self._store.children(i.id)]
        spend = item_cost(all_children)
        escalations = _escalations_on(self._store, input.day)
        backlog_start, backlog_close = _backlog_start_and_close(self._store, input.day)
        row = self._store.day_summary(input.day)
        summary = row.summary if row else None
        return ReportResponse(
            day=input.day, completed=completed, abandoned=abandoned, spend=spend,
            automation_count=automation.count, automation_spend=automation.spend,
            escalations=escalations,
            backlog_start=backlog_start, backlog_close=backlog_close,
            backlog_delta=backlog_close - backlog_start,
            summary=summary,
        )

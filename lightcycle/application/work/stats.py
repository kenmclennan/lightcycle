import datetime
from dataclasses import dataclass

from lightcycle.application.flow.engine_steps import RETRO_ORIGIN_LABEL
from lightcycle.application.work.done import DoneInput, DoneUseCase
from lightcycle.domain.work import ItemCost, item_cost, parse_timestamp


@dataclass(frozen=True)
class StatsInput:
    day: datetime.date


@dataclass(frozen=True)
class StatsResponse:
    day: datetime.date
    completed: int
    abandoned: int
    spend: ItemCost
    audits: int
    escalations: int
    backlog_size: int
    backlog_delta: int


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


def _backlog_size_asof_pair(store, day):
    items = store.all_items_including_done()
    earliest = _earliest_step_created_by_item(store)
    today = _backlog_size_asof(items, earliest, _local_midnight(day))
    yesterday = _backlog_size_asof(items, earliest, _local_midnight(day - datetime.timedelta(days=1)))
    return today, yesterday


def _escalations_on(store, day):
    count = 0
    for node_id, ts in store.waiting_history():
        parsed = parse_timestamp(ts)
        if parsed is not None and parsed.date() == day:
            count += 1
    return count


class StatsUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: StatsInput) -> StatsResponse:
        done_uc = DoneUseCase(self._store)
        closed_today = done_uc.execute(DoneInput(day=input.day)).rows
        items = [r.step for r in closed_today]
        completed = sum(1 for i in items if i.disposition == "completed")
        abandoned = sum(1 for i in items if i.disposition in ("abandoned", "aborted"))
        audits = sum(1 for i in items if RETRO_ORIGIN_LABEL in self._store.labels_of(i.id))
        all_children = [s for i in items for s in self._store.children(i.id)]
        spend = item_cost(all_children)
        escalations = _escalations_on(self._store, input.day)
        backlog_today, backlog_yesterday = _backlog_size_asof_pair(self._store, input.day)
        return StatsResponse(
            day=input.day, completed=completed, abandoned=abandoned, spend=spend,
            audits=audits, escalations=escalations,
            backlog_size=backlog_today, backlog_delta=backlog_today - backlog_yesterday,
        )

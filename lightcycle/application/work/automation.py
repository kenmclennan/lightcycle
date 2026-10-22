import datetime
from dataclasses import dataclass
from typing import Optional

from lightcycle.application.flow.engine_steps import (
    HELD_COMMENT_ORIGIN_LABEL,
    RETRO_ORIGIN_LABEL,
    SCHEDULE_ORIGIN_LABEL,
    SUMMARY_ORIGIN_LABEL,
)
from lightcycle.application.work.item_partition import is_closed_item
from lightcycle.domain.work import ItemCost, item_cost, parse_timestamp

AUTOMATION_LABELS = frozenset(
    {SUMMARY_ORIGIN_LABEL, RETRO_ORIGIN_LABEL, HELD_COMMENT_ORIGIN_LABEL, SCHEDULE_ORIGIN_LABEL})


def is_automation_item(store, item):
    return bool(AUTOMATION_LABELS.intersection(store.labels_of(item.id)))


@dataclass(frozen=True)
class AutomationInput:
    day: Optional[datetime.date] = None


@dataclass(frozen=True)
class AutomationTotal:
    count: int
    spend: ItemCost


def _closed_on(item, day):
    if day is None:
        return True
    parsed = parse_timestamp(item.closed_at)
    return parsed is not None and parsed.date() == day


class AutomationUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: AutomationInput) -> AutomationTotal:
        items = [
            i for i in self._store.all_items_including_done()
            if is_closed_item(i) and _closed_on(i, input.day) and is_automation_item(self._store, i)
        ]
        children = [s for i in items for s in self._store.children(i.id)]
        return AutomationTotal(count=len(items), spend=item_cost(children))

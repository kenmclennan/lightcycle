import datetime
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.application.flow.engine_steps import (
    GOAL_STATE_OF_PLAY_STEP,
    RETRO_ORIGIN_LABEL,
    SUMMARY_ORIGIN_LABEL,
)
from lightcycle.application.work.human_node_row import HumanNodeRow
from lightcycle.application.work.item_partition import is_closed_item
from lightcycle.application.work.project_of import project_of, repo_of
from lightcycle.domain.work import ItemCost, item_cost, node_id_key, parse_timestamp

AUTOMATION_LABELS = frozenset({SUMMARY_ORIGIN_LABEL, RETRO_ORIGIN_LABEL})

KIND_AUDIT = "audit"
KIND_DAILY_SUMMARY = "daily-summary"
KIND_STATE_OF_PLAY = "state-of-play"

KIND_DISPLAY = (
    (KIND_AUDIT, "Audits"),
    (KIND_DAILY_SUMMARY, "Daily summaries"),
    (KIND_STATE_OF_PLAY, "State of play"),
)

_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def is_automation_item(store, item):
    return bool(AUTOMATION_LABELS.intersection(store.labels_of(item.id)))


def automation_kind(store, item):
    labels = store.labels_of(item.id)
    if RETRO_ORIGIN_LABEL in labels:
        return KIND_AUDIT
    if SUMMARY_ORIGIN_LABEL in labels:
        if any(c.stage == GOAL_STATE_OF_PLAY_STEP for c in store.children(item.id)):
            return KIND_STATE_OF_PLAY
        return KIND_DAILY_SUMMARY
    return None


@dataclass(frozen=True)
class AutomationInput:
    day: Optional[datetime.date] = None


@dataclass(frozen=True)
class AutomationTally:
    kind: str
    label: str
    count: int
    spend: ItemCost


@dataclass(frozen=True)
class AutomationResponse:
    rows: List[HumanNodeRow]
    tallies: List[AutomationTally]
    total: AutomationTally


def _closed_on(item, day):
    if day is None:
        return True
    parsed = parse_timestamp(item.closed_at)
    return parsed is not None and parsed.date() == day


def _tally(store, kind, label, items):
    children = [s for i in items for s in store.children(i.id)]
    return AutomationTally(kind=kind, label=label, count=len(items), spend=item_cost(children))


class AutomationUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: AutomationInput) -> AutomationResponse:
        by_kind = {kind: [] for kind, _ in KIND_DISPLAY}
        for item in self._store.all_items_including_done():
            if not is_closed_item(item) or not _closed_on(item, input.day):
                continue
            kind = automation_kind(self._store, item)
            if kind is not None:
                by_kind[kind].append(item)
        items = [i for group in by_kind.values() for i in group]
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
        tallies = [_tally(self._store, kind, label, by_kind[kind]) for kind, label in KIND_DISPLAY]
        return AutomationResponse(rows=rows, tallies=tallies, total=_tally(self._store, "total", "Total", items))

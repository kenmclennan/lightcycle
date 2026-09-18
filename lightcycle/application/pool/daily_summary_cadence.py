import datetime
from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.engine_steps import DAILY_SUMMARY_STEP, SUMMARY_ORIGIN_LABEL
from lightcycle.application.work.done import DoneInput, DoneUseCase
from lightcycle.domain.work import State, parse_timestamp

_SCAN_INTERVAL_SECONDS = 60
_BACKFILL_WINDOW_DAYS = 7
_MIN_TIMESTAMP = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def _local_date(now):
    return datetime.datetime.fromtimestamp(now).astimezone().date()


def _closed_count(store, day):
    counts = {dc.day: dc.count for dc in DoneUseCase(store).day_counts()}
    return counts.get(day, 0)


def _describe_day(store, day):
    rows = DoneUseCase(store).execute(DoneInput(day=day)).rows
    ordered = sorted(rows, key=lambda r: parse_timestamp(r.step.closed_at) or _MIN_TIMESTAMP)
    return "\n".join("%s - %s" % (r.step.id, r.step.title) for r in ordered)


@dataclass(frozen=True)
class DailySummaryCadenceResponse:
    fired: List[str] = field(default_factory=list)


class DailySummaryCadenceUseCase:
    def __init__(self, store, config):
        self._store = store
        self._config = config
        self._last_scan = {}

    def execute(self, now: float) -> DailySummaryCadenceResponse:
        if self._open_summary():
            return DailySummaryCadenceResponse()
        today = _local_date(now)
        for day in (today, today - datetime.timedelta(days=1)):
            tid = self._maybe_fire(day, now)
            if tid:
                return DailySummaryCadenceResponse(fired=[tid])
        return DailySummaryCadenceResponse()

    def _maybe_fire(self, day, now):
        row = self._store.day_summary(day)
        dirty_since = row.dirty_since if row else None
        if dirty_since is None:
            last = self._last_scan.get(day)
            if last is not None and now - last < _SCAN_INTERVAL_SECONDS:
                return None
            self._last_scan[day] = now
            summarized = row.summarized_count if row else 0
            if _closed_count(self._store, day) <= summarized:
                return None
            self._store.mark_day_summary_dirty(day)
            return None
        since = parse_timestamp(dirty_since)
        elapsed = (datetime.datetime.fromtimestamp(now).astimezone() - since).total_seconds()
        if elapsed < self._config.daily_summary_debounce_seconds():
            return None
        return self._spawn(day)

    def _spawn(self, day):
        row = self._store.day_summary(day)
        if row and row.step_id:
            return None
        count = _closed_count(self._store, day)
        title = "Daily summary: %s" % day.isoformat()
        description = _describe_day(self._store, day)
        with self._store.transaction():
            self._store.mark_day_summary_dirty(day)
            item_id = self._store.create_item(
                title, description, shortcode=self._config.internal_shortcode())
            self._store.label_add(item_id, SUMMARY_ORIGIN_LABEL)
            tid = self._store.create_step(step=DAILY_SUMMARY_STEP, role="agent", parent=item_id)
            self._store.start_day_summary(day, step_id=tid, spawn_count=count)
        return tid

    def _open_summary(self):
        return any(s.state != State.DONE for s in self._store.steps_at_step(DAILY_SUMMARY_STEP))

    def backfill(self, now):
        today = _local_date(now)
        spawned = []
        for n in range(1, _BACKFILL_WINDOW_DAYS + 1):
            day = today - datetime.timedelta(days=n)
            row = self._store.day_summary(day)
            summarized = row.summarized_count if row else 0
            if _closed_count(self._store, day) <= summarized:
                continue
            tid = self._spawn(day)
            if tid:
                spawned.append((day, tid))
        return spawned

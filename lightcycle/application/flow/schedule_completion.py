import datetime

from lightcycle.domain.feedback import RETROED_LABEL
from lightcycle.domain.schedule.state import (
    SCHEDULE_STATE_ARTIFACT,
    parse_batch_state,
    parse_day_state,
)

SUMMARY_ARTIFACT = "summary"
DONE_OUTCOME = "done"


class ScheduleCompletion:
    def __init__(self, store):
        self._store = store

    def execute(self, step, outcome):
        artifacts = self._store.item_artifacts(step.item)
        state = next((a.value for a in artifacts if a.type == SCHEDULE_STATE_ARTIFACT), None)
        if state is None:
            return
        batch = parse_batch_state(state)
        if batch is not None:
            self._retro_batch(step, batch)
            return
        day = parse_day_state(state)
        if day is not None and outcome == DONE_OUTCOME:
            summary = next((a.value for a in artifacts if a.type == SUMMARY_ARTIFACT), None)
            if summary:
                self._finish_day(day, summary)

    def _retro_batch(self, step, batch):
        unretroed = {i.id for i in self._store.closed_unretroed_items()}
        unretroed.update(p.id for p in self._store.closed_unretroed_passes())
        marked = [node_id for node_id in batch if node_id in unretroed]
        for node_id in marked:
            self._store.label_add(node_id, RETROED_LABEL)
        self._store.note(step.id, "retroed: %d of %d" % (len(marked), len(batch)))

    def _finish_day(self, day_state, summary):
        day = datetime.date.fromisoformat(day_state[0])
        self._store.mark_day_summary_dirty(day)
        row = self._store.day_summary(day)
        existing = row.summarized_count if row else 0
        self._store.finish_day_summary(
            day, summary=summary, summarized_count=max(existing, day_state[1]),
            clear_dirty=True)

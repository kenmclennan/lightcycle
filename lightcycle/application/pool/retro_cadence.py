from dataclasses import dataclass, field
from typing import List

from lightcycle.application.work.pending_reflections import (
    item_reflection_count,
    pending_reflection_count,
)
from lightcycle.domain.audit import AUDIT_STEP
from lightcycle.domain.work import State


@dataclass(frozen=True)
class RetroCadenceResponse:
    fired: List[str] = field(default_factory=list)


class RetroCadenceUseCase:

    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, now: float) -> RetroCadenceResponse:
        interval = self._config.retro_interval_reflections()
        if pending_reflection_count(self._store) < interval or self._open_audit():
            return RetroCadenceResponse()

        batch = [
            item for item in self._store.closed_unretroed_items()
            if item_reflection_count(self._store, item) > 0
        ]
        title = "Audit of %d closed items" % len(batch)
        item_id = self._store.create_item(title)
        self._store.edit_node(
            item_id, description="batch: %s" % ", ".join(sorted(i.id for i in batch)))
        self._store.label_add(item_id, "retro-origin")
        tid = self._store.create_step(
            "%s: %s" % (AUDIT_STEP, title),
            step=AUDIT_STEP, role="agent", parent=item_id)
        return RetroCadenceResponse(fired=[tid])

    def _open_audit(self):
        return any(s.state != State.DONE for s in self._store.steps_at_step(AUDIT_STEP))

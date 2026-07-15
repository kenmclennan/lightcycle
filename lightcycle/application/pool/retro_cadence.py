from dataclasses import dataclass, field
from typing import List

from lightcycle.application.work.has_feedback import has_feedback
from lightcycle.domain.work import State

_BATCH_TITLE = "pending-feedback"


@dataclass(frozen=True)
class RetroCadenceResponse:
    fired: List[str] = field(default_factory=list)


class RetroCadenceUseCase:

    def __init__(self, store, flow_service, config):
        self._store = store
        self._flow_service = flow_service
        self._config = config

    def execute(self, now: float) -> RetroCadenceResponse:
        interval = self._config.retro_interval_items()
        flow = self._flow_service.load_flow()
        cadence_steps = flow.retro_cadence_steps()
        if not cadence_steps:
            return RetroCadenceResponse()

        pending = [
            item for item in self._store.closed_unretroed_items()
            if has_feedback(self._store, item)
        ]

        fired = []
        for step, role in cadence_steps:
            if len(pending) < interval or self._open_audit(step):
                continue
            item_id = self._store.create_item(_BATCH_TITLE)
            self._store.label_add(item_id, "retro-origin")
            tid = self._store.create_step(
                "%s: %s" % (step, _BATCH_TITLE), step=step, role=role, parent=item_id)
            fired.append(tid)

        return RetroCadenceResponse(fired=fired)

    def _open_audit(self, step):
        return any(s.state != State.DONE for s in self._store.steps_at_step(step))

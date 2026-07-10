import datetime
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class RetroCadenceResponse:
    fired: List[str] = field(default_factory=list)


def _date_str(ts: float) -> str:
    return datetime.date.fromtimestamp(ts).isoformat()


class RetroCadenceUseCase:

    def __init__(self, store, flow_service, config):
        self._store = store
        self._flow_service = flow_service
        self._config = config

    def execute(self, now: float) -> RetroCadenceResponse:
        interval_items = self._config.retro_interval_items()
        flow = self._flow_service.load_flow()
        cadence_steps = flow.retro_cadence_steps()
        if not cadence_steps:
            return RetroCadenceResponse()

        fired = []
        for step, role in cadence_steps:
            reference = self._last_fire_reference(step)
            if reference is None:
                continue
            items = self._store.items_closed_since(reference)
            if len(items) < interval_items:
                continue
            tid = self._store.create_step(
                "%s: closed-work trend audit" % step, step=step, role=role)
            self._store.update_metadata(tid, {"since": reference, "fired_at": _date_str(now)})
            fired.append(tid)

        return RetroCadenceResponse(fired=fired)

    def _last_fire_reference(self, step) -> Optional[str]:
        max_fired_at = None
        for s in self._store.steps_at_step(step):
            if s.fired_at and (max_fired_at is None or s.fired_at > max_fired_at):
                max_fired_at = s.fired_at
        if max_fired_at:
            return max_fired_at
        return self._oldest_closed_item_date()

    def _oldest_closed_item_date(self) -> Optional[str]:
        items = self._store.last_n_closed_items(1000)
        if not items:
            return None
        dates = [i.closed_at[:10] for i in items if i.closed_at]
        return min(dates) if dates else None

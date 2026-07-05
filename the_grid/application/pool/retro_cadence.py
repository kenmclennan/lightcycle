import datetime
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class RetroCadenceResponse:
    fired: List[str] = field(default_factory=list)


def _date_str(ts: float) -> str:
    return datetime.date.fromtimestamp(ts).isoformat()


def _days_between(later_str: str, earlier_str: str) -> int:
    later = datetime.date.fromisoformat(later_str)
    earlier = datetime.date.fromisoformat(earlier_str)
    return (later - earlier).days


class RetroCadenceUseCase:

    def __init__(self, store, flow_service, config):
        self._store = store
        self._flow_service = flow_service
        self._config = config

    def execute(self, now: float) -> RetroCadenceResponse:
        interval_days = self._config.retro_interval_days()
        min_epics = self._config.retro_min_epics()
        flow = self._flow_service.load_flow()
        cadence_steps = flow.retro_cadence_steps()
        if not cadence_steps:
            return RetroCadenceResponse()

        now_date = _date_str(now)
        fired = []

        for step, role in cadence_steps:
            reference = self._last_fire_reference(step)
            if reference is None:
                continue
            elapsed = _days_between(now_date, reference)
            if elapsed < interval_days:
                continue
            epics = self._store.epics_closed_since(reference)
            if len(epics) < min_epics:
                continue
            tid = self._store.create_task(
                "%s: cross-epic trend audit" % step, step=step, role=role)
            self._store.update_metadata(tid, {"since": reference, "fired_at": now_date})
            fired.append(tid)

        return RetroCadenceResponse(fired=fired)

    def _last_fire_reference(self, step) -> Optional[str]:
        max_fired_at = None
        for task in self._store.tasks_at_step(step):
            if task.fired_at and (max_fired_at is None or task.fired_at > max_fired_at):
                max_fired_at = task.fired_at
        if max_fired_at:
            return max_fired_at
        return self._oldest_closed_epic_date()

    def _oldest_closed_epic_date(self) -> Optional[str]:
        epics = self._store.last_n_closed_epics(1000)
        if not epics:
            return None
        dates = [e.closed_at[:10] for e in epics if e.closed_at]
        return min(dates) if dates else None

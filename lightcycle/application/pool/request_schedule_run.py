from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.application.pool.schedule_resolution import ScheduleResolver, schedule_label
from lightcycle.config import ConfigError
from lightcycle.domain.schedule.schedule import SOURCE_BUNDLE
from lightcycle.domain.work import State


@dataclass(frozen=True)
class RequestScheduleRunResponse:
    schedule_id: str


class RequestScheduleRunUseCase:
    def __init__(self, store, config, flow, workflow_source):
        self._store = store
        self._config = config
        self._resolver = ScheduleResolver(store, config, flow, workflow_source)

    def _paused(self):
        try:
            return self._config.schedules_paused()
        except ConfigError:
            return True

    def execute(self, schedule_id: str) -> RequestScheduleRunResponse:
        resolved = next(
            (r for r in self._resolver.resolve() if r.schedule.id == schedule_id), None)
        if resolved is None or resolved.schedule.source == SOURCE_BUNDLE:
            raise UseCaseError("no schedule-%s block in config" % schedule_id)
        schedule = resolved.schedule
        if not schedule.enabled:
            raise UseCaseError("schedule %s is not enabled" % schedule_id)
        if resolved.problem:
            raise UseCaseError("schedule %s is invalid: %s" % (schedule_id, resolved.problem))
        if self._paused():
            raise UseCaseError("schedules-paused is on, so schedule %s cannot run" % schedule_id)
        open_items = [
            i for i in self._store.items_with_label(schedule_label(schedule_id))
            if i.state != State.DONE]
        if open_items:
            raise UseCaseError(
                "schedule %s already has open item %s" % (schedule_id, open_items[0].id))
        self._store.request_schedule_run(schedule_id)
        return RequestScheduleRunResponse(schedule_id=schedule_id)

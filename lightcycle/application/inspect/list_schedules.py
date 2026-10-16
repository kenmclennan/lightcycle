import datetime
from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.pool.schedule_cadence import last_fire_of
from lightcycle.application.pool.schedule_guards import GUARD_FAILURES, GuardUnreadable, ScheduleGuards
from lightcycle.application.pool.schedule_resolution import ScheduleResolver, schedule_label
from lightcycle.config import ConfigError
from lightcycle.domain.schedule.cron import next_due
from lightcycle.domain.schedule.guards import is_script_guard
from lightcycle.domain.schedule.schedule import SOURCE_BUNDLE
from lightcycle.domain.work import State

STATE_ON = "on"
STATE_OFF = "off"
STATE_PAUSED = "paused"
NEVER = "never"
NONE = "-"
SCRIPT_GUARD_LISTING = "script guard: evaluated by the pool, not by this listing"


@dataclass(frozen=True)
class ScheduleRow:
    id: str
    source: str
    state: str
    reason: str
    workflow: Optional[str]
    project: Optional[str]
    cron: Optional[str]
    guard: Optional[str]
    last_fire: str
    next_fire: str
    guard_result: str

    def as_dict(self):
        return dict(self.__dict__)


@dataclass(frozen=True)
class ListSchedulesInput:
    now: float


@dataclass(frozen=True)
class ListSchedulesResponse:
    rows: List[ScheduleRow] = field(default_factory=list)


class ListSchedulesUseCase:
    def __init__(self, store, config, flow, workflow_source, git):
        self._store = store
        self._config = config
        self._resolver = ScheduleResolver(store, config, flow, workflow_source)
        self._guards = ScheduleGuards(store, git, workflow_source)

    def _paused(self):
        try:
            return self._config.schedules_paused(), "schedules-paused is true in config"
        except ConfigError:
            return True, "schedules-paused is unreadable in config, so schedules are paused"

    def execute(self, input: ListSchedulesInput) -> ListSchedulesResponse:
        now_local = datetime.datetime.fromtimestamp(input.now).astimezone().replace(tzinfo=None)
        paused, paused_reason = self._paused()
        rows = []
        for resolved in self._resolver.resolve():
            schedule = resolved.schedule
            firings = self._store.items_with_label(schedule_label(schedule.id))
            state, reason = self._state(resolved, firings, paused, paused_reason)
            last = last_fire_of(firings)
            rows.append(ScheduleRow(
                id=schedule.id, source=schedule.source, state=state, reason=reason,
                workflow=schedule.workflow, project=schedule.project, cron=schedule.cron,
                guard=schedule.guard,
                last_fire=last.isoformat(sep=" ", timespec="minutes") if last else NEVER,
                next_fire=self._next_fire(schedule, now_local),
                guard_result=self._guard_result(resolved, firings, now_local),
            ))
        return ListSchedulesResponse(rows=rows)

    def _state(self, resolved, firings, paused, paused_reason):
        schedule = resolved.schedule
        if not schedule.enabled:
            if schedule.source == SOURCE_BUNDLE:
                return STATE_OFF, "bundle suggestion, not enabled in config"
            if schedule.explicit_off:
                return STATE_OFF, "config sets enabled: false"
            return STATE_OFF, "invalid: %s" % resolved.problem
        if paused:
            return STATE_PAUSED, paused_reason
        if resolved.problem:
            return STATE_ON, "invalid: %s" % resolved.problem
        open_items = [i for i in firings if i.state != State.DONE]
        if open_items:
            return STATE_ON, "open item %s blocks firing" % open_items[0].id
        return STATE_ON, "waiting for next due time"

    def _next_fire(self, schedule, now_local):
        if not schedule.cron or schedule.problem:
            return NONE
        due = next_due(schedule.cron, now_local)
        return due.isoformat(sep=" ", timespec="minutes") if due else NONE

    def _guard_result(self, resolved, firings, now_local):
        schedule = resolved.schedule
        if schedule.problem:
            return NONE
        if is_script_guard(schedule.guard):
            return SCRIPT_GUARD_LISTING
        try:
            result = self._guards.evaluate(schedule.guard, schedule.params, firings, now_local)
        except GuardUnreadable as e:
            return "not passed: %s" % e
        except GUARD_FAILURES as e:
            return "not passed: guard %s failed: %s" % (schedule.guard, e)
        return "%s: %s" % ("passed" if result.passed else "not passed", result.detail)

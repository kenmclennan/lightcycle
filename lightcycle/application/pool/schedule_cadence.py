import datetime
import sys
from dataclasses import dataclass, field
from typing import List, Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.engine_steps import SCHEDULE_ORIGIN_LABEL
from lightcycle.application.pool.schedule_guards import (
    SCHEDULE_STATE_ARTIFACT,
    GUARD_FAILURES,
    GuardUnreadable,
    ScheduleGuards,
)
from lightcycle.application.pool.schedule_resolution import ScheduleResolver, schedule_label
from lightcycle.application.work.activate_item import ActivateItemInput
from lightcycle.config import ConfigError
from lightcycle.domain.schedule.cron import previous_due
from lightcycle.domain.work import State, parse_timestamp

PAUSED = "paused"


@dataclass(frozen=True)
class ScheduleCadenceResponse:
    fired: List[str] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)


def local_naive(timestamp):
    return parse_timestamp(timestamp).astimezone().replace(tzinfo=None)


def last_fire_of(firings):
    created = [local_naive(i.created_at) for i in firings]
    return max(created) if created else None


class ScheduleCadenceUseCase:
    def __init__(self, store, config, flow, workflow_source, git, activate):
        self._store = store
        self._config = config
        self._resolver = ScheduleResolver(store, config, flow, workflow_source)
        self._guards = ScheduleGuards(store, git, workflow_source)
        self._activate = activate
        self._evaluated = {}
        self._warned = {}

    def reset(self):
        self._evaluated.clear()
        self._warned.clear()

    def _paused(self):
        try:
            return self._config.schedules_paused()
        except ConfigError:
            return True

    def _warn(self, schedule_id, reason):
        if self._warned.get(schedule_id) == reason:
            return
        self._warned[schedule_id] = reason
        sys.stderr.write("warning: schedule %s skipped: %s\n" % (schedule_id, reason))

    def execute(self, now: float) -> ScheduleCadenceResponse:
        if self._paused():
            blocks = self._config.schedule_blocks()
            return ScheduleCadenceResponse(skipped=[
                (sid, PAUSED) for sid, block in blocks.items()
                if str(block.get("enabled", "")).strip().lower() in ("true", "yes", "1", "on")
            ])
        now_local = datetime.datetime.fromtimestamp(now).astimezone().replace(tzinfo=None)
        fired, skipped = [], []
        for resolved in self._resolver.resolve():
            schedule = resolved.schedule
            if not schedule.enabled:
                continue
            if resolved.problem:
                self._warn(schedule.id, resolved.problem)
                skipped.append((schedule.id, resolved.problem))
                continue
            outcome = self._tick_one(resolved, now_local)
            if outcome[0] == "fired":
                fired.append(outcome[1])
            elif outcome[1]:
                skipped.append((schedule.id, outcome[1]))
        return ScheduleCadenceResponse(fired=fired, skipped=skipped)

    def _tick_one(self, resolved, now_local):
        schedule = resolved.schedule
        firings = self._store.items_with_label(schedule_label(schedule.id))
        open_items = [i for i in firings if i.state != State.DONE]
        if open_items:
            return ("skipped", "open item %s" % open_items[0].id)
        due = previous_due(schedule.cron, now_local)
        last_fire = last_fire_of(firings)
        if due is None or (last_fire is not None and due <= last_fire):
            return ("skipped", "")
        if self._evaluated.get(schedule.id) == due:
            return ("skipped", "")
        try:
            result = self._guards.evaluate(schedule.guard, schedule.params, firings, now_local)
        except GuardUnreadable as e:
            self._warn(schedule.id, str(e))
            return ("skipped", str(e))
        except GUARD_FAILURES as e:
            reason = "guard %s failed: %s" % (schedule.guard, e)
            self._warn(schedule.id, reason)
            return ("skipped", reason)
        self._evaluated[schedule.id] = due
        if not result.passed:
            return ("skipped", "")
        return self._file(resolved, result)

    def _file(self, resolved, result):
        schedule = resolved.schedule
        with self._store.transaction():
            item_id = self._store.create_item(
                result.title, result.description, project=resolved.project_name,
                workflow=schedule.workflow, shortcode=resolved.shortcode)
            self._store.add_artifact(item_id, "repo", resolved.identity)
            self._store.label_add(item_id, SCHEDULE_ORIGIN_LABEL)
            self._store.label_add(item_id, schedule_label(schedule.id))
            for label in schedule.labels:
                self._store.label_add(item_id, label)
            self._store.add_artifact(
                item_id, SCHEDULE_STATE_ARTIFACT, result.state, internal=True)
        try:
            self._activate.execute(ActivateItemInput(item=item_id))
        except UseCaseError as e:
            reason = "filed %s but could not activate it: %s" % (item_id, e)
            self._warn(schedule.id, reason)
            return ("skipped", reason)
        return ("fired", item_id)

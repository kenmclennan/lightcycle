import datetime
import os
import sys
from dataclasses import dataclass, field
from typing import List, Tuple

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.engine_steps import SCHEDULE_GUARD_LABEL_PREFIX, SCHEDULE_ORIGIN_LABEL
from lightcycle.application.pool.schedule_guards import (
    SCHEDULE_STATE_ARTIFACT,
    GUARD_FAILURES,
    GuardResult,
    GuardUnreadable,
    ScheduleGuards,
    firing_states,
)
from lightcycle.application.pool.schedule_resolution import ScheduleResolver, schedule_label
from lightcycle.application.work.activate_item import ActivateItemInput
from lightcycle.application.workflows.script_tooling import (
    describe_violation,
    result_violation,
    stdin_for_guard,
)
from lightcycle.config import ConfigError
from lightcycle.domain.schedule.cron import previous_due
from lightcycle.domain.schedule.guards import is_script_guard, script_guard_path
from lightcycle.domain.work import State, guard_log_label, parse_timestamp
from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.domain.workflows.script_stage import parse_guard_output

PAUSED = "paused"
GUARD_KEY_PREFIX = "guard:"
EVALUATING = "evaluating"


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
    def __init__(self, store, config, flow, workflow_source, git, activate, runner, lifecycle):
        self._store = store
        self._config = config
        self._resolver = ScheduleResolver(store, config, flow, workflow_source)
        self._guards = ScheduleGuards(store, git, workflow_source)
        self._activate = activate
        self._workflow_source = workflow_source
        self._runner = runner
        self._lifecycle = lifecycle
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
        reaped = self._reap_guards()
        if self._paused():
            blocks = self._config.schedule_blocks()
            return ScheduleCadenceResponse(fired=reaped, skipped=[
                (sid, PAUSED) for sid, block in blocks.items()
                if str(block.get("enabled", "")).strip().lower() in ("true", "yes", "1", "on")
            ])
        now_local = datetime.datetime.fromtimestamp(now).astimezone().replace(tzinfo=None)
        fired, skipped = list(reaped), []
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
        requested = self._store.schedule_run_requested(schedule.id)
        due = previous_due(schedule.cron, now_local)
        if not requested:
            last_fire = last_fire_of(firings)
            if due is None or (last_fire is not None and due <= last_fire):
                return ("skipped", "")
            if self._evaluated.get(schedule.id) == due:
                return ("skipped", "")
        if is_script_guard(schedule.guard):
            return self._start_script_guard(resolved, due, firings, requested)
        try:
            result = self._guards.evaluate(schedule.guard, schedule.params, firings, now_local)
        except GuardUnreadable as e:
            self._warn(schedule.id, str(e))
            return ("skipped", str(e))
        except GUARD_FAILURES as e:
            reason = "guard %s failed: %s" % (schedule.guard, e)
            self._warn(schedule.id, reason)
            return ("skipped", reason)
        if requested:
            self._store.clear_schedule_run_request(schedule.id)
            if not result.passed:
                sys.stderr.write("schedule %s run request not fired: guard %s did not pass: %s\n" % (
                    schedule.id, schedule.guard, result.detail))
        else:
            self._evaluated[schedule.id] = due
        if not result.passed:
            return ("skipped", "")
        return self._file(resolved, result)

    def _start_script_guard(self, resolved, due, firings, requested=False):
        schedule = resolved.schedule
        key = GUARD_KEY_PREFIX + schedule.id
        if key in self._runner.running():
            return ("skipped", EVALUATING)
        parsed = parse_pin(resolved.pin) if resolved.pin else None
        if parsed is None:
            reason = "script guard needs a pinned workflow"
            self._warn(schedule.id, reason)
            return ("skipped", reason)
        origin, name, sha = parsed
        extra = {"LC_SCHEDULE_ID": schedule.id}
        for param, value in schedule.params.items():
            extra["LC_SCHEDULE_PARAM_%s" % param.upper().replace("-", "_")] = str(value)
        bundle_dir = self._workflow_source.pinned_bundle(origin, sha)
        env, missing = self._lifecycle.script_environment(
            origin, name, sha, bundle_dir, "guard", extra)
        if missing:
            reason = "script guard needs config key(s) %s in %s" % (
                ", ".join(missing), self._config.workflow_config_block_name(origin, name))
            self._warn(schedule.id, reason)
            return ("skipped", reason)
        cwd = self._lifecycle.ensure_data_dir(origin, name)
        states = firing_states(self._store, firings)
        last_state = states[-1][1] if states else None
        script = os.path.join(bundle_dir, *script_guard_path(schedule.guard).split("/"))
        if requested:
            self._store.clear_schedule_run_request(schedule.id)
        else:
            self._evaluated[schedule.id] = due
        self._runner.start(
            key, script, cwd, env, stdin_for_guard(schedule.id, last_state),
            self._config.script_timeout_seconds(), guard_log_label(schedule.id))
        return ("skipped", EVALUATING)

    def _reap_guards(self):
        fired = []
        resolved_by_id = None
        for key in self._runner.running():
            if not key.startswith(GUARD_KEY_PREFIX):
                continue
            result = self._runner.poll(key)
            if result is None:
                continue
            schedule_id = key[len(GUARD_KEY_PREFIX):]
            label = "script guard for schedule %s" % schedule_id
            reason, ok = result_violation(result, self._config.script_timeout_seconds())
            output = None
            if ok:
                try:
                    output = parse_guard_output(result.stdout)
                except ValueError as e:
                    reason = "broke the output contract: %s" % e
            if output is None:
                self._warn(schedule_id, describe_violation(label, reason, result, True))
                continue
            if not output.passed:
                continue
            if resolved_by_id is None:
                resolved_by_id = {r.schedule.id: r for r in self._resolver.resolve()}
            resolved = resolved_by_id.get(schedule_id)
            if resolved is None or not self._still_fireable(resolved):
                continue
            outcome = self._file(resolved, GuardResult(
                True, output.note, output.title, output.description, output.state))
            if outcome[0] == "fired":
                if result.log_path:
                    self._record_guard_log(outcome[1], result.log_path)
                fired.append(outcome[1])
        return fired

    def _record_guard_log(self, item_id, log_path):
        first = sorted(
            (c for c in self._store.children(item_id) if c.type == "step"),
            key=lambda c: c.created_at or "",
        )
        if first:
            self._store.set_log(first[0].id, log_path)

    def _still_fireable(self, resolved):
        schedule = resolved.schedule
        if not schedule.enabled or resolved.problem or self._paused():
            return False
        firings = self._store.items_with_label(schedule_label(schedule.id))
        return not any(i.state != State.DONE for i in firings)

    def _file(self, resolved, result):
        schedule = resolved.schedule
        with self._store.transaction():
            item_id = self._store.create_item(
                result.title, result.description, project=schedule.name or resolved.project_name,
                workflow=schedule.workflow, shortcode=resolved.shortcode)
            self._store.add_artifact(item_id, "repo", resolved.identity)
            self._store.label_add(item_id, SCHEDULE_ORIGIN_LABEL)
            self._store.label_add(item_id, schedule_label(schedule.id))
            self._store.label_add(item_id, SCHEDULE_GUARD_LABEL_PREFIX + schedule.guard)
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

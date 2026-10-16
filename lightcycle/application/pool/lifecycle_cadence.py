import datetime
import sys
from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.engine_steps import (
    LIFECYCLE_FAILURE_STEP,
    LIFECYCLE_ORIGIN_LABEL,
)
from lightcycle.application.workflows.lifecycle import describe_result
from lightcycle.domain.schedule.cron import parse_cron, previous_due
from lightcycle.domain.work import State
from lightcycle.domain.workflows.lifecycle import missing_required_keys


@dataclass(frozen=True)
class LifecycleCadenceResponse:
    started: List[str] = field(default_factory=list)
    reaped: List[str] = field(default_factory=list)
    filed: List[str] = field(default_factory=list)


def lifecycle_key(origin, name):
    return "%s/%s" % (origin, name)


def lifecycle_label(key):
    return "lifecycle:%s" % key


class LifecycleCadenceUseCase:
    def __init__(self, store, config, source, lifecycle, runner, shortcode):
        self._store = store
        self._config = config
        self._source = source
        self._lifecycle = lifecycle
        self._runner = runner
        self._shortcode = shortcode
        self._warned = {}

    def reset(self):
        self._warned.clear()

    def in_flight(self):
        return list(self._runner.running())

    def _warn(self, key, reason):
        if self._warned.get(key) == reason:
            return
        self._warned[key] = reason
        sys.stderr.write("warning: maintain %s skipped: %s\n" % (key, reason))

    def execute(self, now: float) -> LifecycleCadenceResponse:
        reaped, filed = self._reap()
        started = self._start(now)
        return LifecycleCadenceResponse(started=started, reaped=reaped, filed=filed)

    def _reap(self):
        reaped, filed = [], []
        for key in self._runner.running():
            result = self._runner.poll(key)
            if result is None:
                continue
            reaped.append(key)
            if result.ok:
                continue
            origin, _, name = key.partition("/")
            item = self._file_failure(key, describe_result(
                origin, name, "maintain", result, self._config.lifecycle_timeout_seconds()))
            if item is not None:
                filed.append(item)
        return reaped, filed

    def _file_failure(self, key, detail):
        label = lifecycle_label(key)
        if any(i.state != State.DONE for i in self._store.items_with_label(label)):
            return None
        with self._store.transaction():
            item_id = self._store.create_item(
                "Maintenance failed for workflow %s" % key, detail,
                shortcode=self._shortcode())
            self._store.label_add(item_id, LIFECYCLE_ORIGIN_LABEL)
            self._store.label_add(item_id, label)
            self._store.create_step(step=LIFECYCLE_FAILURE_STEP, role="human", parent=item_id)
        return item_id

    def _start(self, now):
        now_local = datetime.datetime.fromtimestamp(now).astimezone().replace(tzinfo=None)
        running = set(self._runner.running())
        started = []
        for origin in self._source.list_origins():
            registration = self._source.read_registry(origin)
            if registration is None or not registration.current:
                continue
            sha = registration.current
            for name in self._source.workflow_names(origin, sha):
                key = lifecycle_key(origin, name)
                if key in running:
                    continue
                if self._start_one(origin, name, sha, key, now_local):
                    started.append(key)
        return started

    def _start_one(self, origin, name, sha, key, now_local):
        try:
            declared = self._lifecycle.declared(origin, name, sha)
        except ValueError as e:
            self._warn(key, str(e))
            return False
        if declared is None or not declared.maintain:
            return False
        try:
            parse_cron(declared.cron)
        except ValueError as e:
            self._warn(key, "invalid cron %r: %s" % (declared.cron, e))
            return False
        due = previous_due(declared.cron, now_local)
        if due is None:
            return False
        recorded = self._runner.last_due(key)
        if recorded is None:
            self._runner.record_due(key, due)
            return False
        if due <= recorded:
            return False
        missing = missing_required_keys(declared, self._config.workflow_config(origin, name))
        if missing:
            self._warn(key, "missing required config key(s) %s in %s" % (
                ", ".join(missing), self._config.workflow_config_block_name(origin, name)))
            return False
        script, data_dir, env = self._lifecycle.hook_invocation(
            "maintain", origin, name, sha, lifecycle=declared)
        self._runner.record_due(key, due)
        self._runner.ensure_data_dir(data_dir)
        self._runner.start(key, script, data_dir, env, self._config.lifecycle_timeout_seconds())
        return True

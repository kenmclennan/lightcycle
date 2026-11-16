import json
from dataclasses import dataclass, field
from typing import List

from lightcycle.application.errors import UseCaseError
from lightcycle.application.pool.pr_lookups import flow_for, skip_unpinned
from lightcycle.application.setup.project_registry import ProjectRegistry
from lightcycle.application.work.callout_hold import callout_runs_of
from lightcycle.application.work.stack_layers import StackLayers
from lightcycle.domain.pool.sleep import overlaps_sleep
from lightcycle.domain.work import State, callout_log_label
from lightcycle.domain.work.callout_preflight import (
    failure_message,
    preflight_errors,
    preflight_timeout,
)
from lightcycle.domain.work.callout_response import (
    PROTOCOL,
    CalloutResponse,
    validate_callout_response,
)
from lightcycle.domain.work.callout_runs import (
    CALLOUT_RUNS,
    INTERRUPTED_MESSAGE,
    PHASE_PREFLIGHT,
    PHASE_RUN,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_RUNNING,
    dump_runs,
)
from lightcycle.domain.work.step_focus import FOCUS_ARTIFACT, parse_presents
from lightcycle.ports.github import PrView
from lightcycle.ports.store import NodeNotFoundError, ProjectResolutionError

CALLOUT_KEY_PREFIX = "callout:"
_CALLOUT_ERRORS = (
    OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError, UseCaseError,
    NodeNotFoundError,
)


@dataclass(frozen=True)
class CalloutDispatchResponse:
    started: List[str] = field(default_factory=list)
    reaped: List[str] = field(default_factory=list)


def callout_key(step_id, callout_id, phase=PHASE_RUN):
    key = "%s%s:%s" % (CALLOUT_KEY_PREFIX, step_id, callout_id)
    return key + ":preflight" if phase == PHASE_PREFLIGHT else key


class CalloutDispatchUseCase:
    def __init__(self, store, flow_service, config, runner, github, worktrees):
        self._store = store
        self._flow_service = flow_service
        self._config = config
        self._runner = runner
        self._github = github
        self._worktrees = worktrees
        self._stack = StackLayers(github)

    def execute(self, now: float, sleeps=()) -> CalloutDispatchResponse:
        reaped = self._reap(now, sleeps)
        started = self._start(now)
        return CalloutDispatchResponse(started=started, reaped=reaped)

    def _write(self, step_id, runs):
        self._store.replace_artifact(step_id, CALLOUT_RUNS, dump_runs(runs), internal=True)

    def _record_failure(self, step_id, callout_id, record, message, now, errors=()):
        record = dict(record)
        message = failure_message(message, errors)
        record.update(
            status=STATUS_FAILED, message=message, artifacts=[], finished=now,
            errors=[{"message": e.message, "fix": e.fix} for e in errors])
        self._store.note_condition(step_id, "callout:%s: failed - %s" % (callout_id, message))
        return record

    def _reap(self, now, sleeps=()):
        reaped = []
        running = set(self._runner.running())
        for step in self._store.all_steps():
            runs = callout_runs_of(self._store, step.id)
            changed = False
            for callout_id, record in list(runs.items()):
                if not isinstance(record, dict) or record.get("status") != STATUS_RUNNING:
                    continue
                key = callout_key(step.id, callout_id, record.get("phase", PHASE_RUN))
                try:
                    updated = self._reap_one(
                        step, callout_id, record, key, key in running, now, sleeps)
                except _CALLOUT_ERRORS as e:
                    updated = self._record_failure(step.id, callout_id, record, str(e), now)
                if updated is None:
                    continue
                runs[callout_id] = updated
                changed = True
                reaped.append(key)
            if changed:
                self._write(step.id, runs)
        return reaped

    def _reap_one(self, step, callout_id, record, key, is_running, now, sleeps=()):
        if not is_running:
            return self._record_failure(step.id, callout_id, record, INTERRUPTED_MESSAGE, now)
        result = self._runner.poll(key)
        if result is None:
            return None
        if self._cut_short(record, result, sleeps):
            restarted = self._restart(step, callout_id, record, now)
            if restarted is not None:
                return restarted
        if record.get("phase") == PHASE_PREFLIGHT:
            return self._reap_preflight(step, callout_id, record, result, now)
        if result.timed_out:
            return self._record_failure(
                step.id, callout_id, record,
                "timed out after %ss" % (record.get("timeout") or "the configured limit"), now)
        if result.exit_code is None:
            return self._record_failure(
                step.id, callout_id, record,
                "could not run the command: %s" % (result.stderr_tail or "no exit status"), now)
        if result.exit_code != 0:
            return self._record_failure(
                step.id, callout_id, record, "exited with code %s" % result.exit_code, now)
        parsed = validate_callout_response(result.stdout)
        if not isinstance(parsed, CalloutResponse):
            return self._record_failure(
                step.id, callout_id, record, "invalid response: %s" % parsed, now)
        if parsed.status == STATUS_FAILED:
            return self._record_failure(
                step.id, callout_id, record, parsed.message, now, parsed.errors)
        record = dict(record)
        record.update(
            status=STATUS_OK, message=parsed.message or None, finished=now,
            artifacts=[
                {"label": a.label, "kind": a.kind, "value": a.value} for a in parsed.artifacts])
        return record

    def _cut_short(self, record, result, sleeps):
        return bool(
            result.timed_out and not record.get("suspend_retried")
            and result.started_at is not None and result.finished_at is not None
            and overlaps_sleep(result.started_at, result.finished_at, sleeps))

    def _restart(self, step, callout_id, record, now):
        callout = self._callout(callout_id)
        presents = self._presents(step)
        if callout is None or presents is None:
            return None
        preflight = record.get("phase") == PHASE_PREFLIGHT
        verb = "preflight" if preflight else "run"
        limit = record.get("preflight_timeout") if preflight else callout.timeout
        key = callout_key(step.id, callout_id, PHASE_PREFLIGHT if preflight else PHASE_RUN)
        self._runner.start(
            key, callout.command, self._cwd(step), self._config.base_env(),
            json.dumps(self._request(step, callout, presents, verb)), limit,
            callout_log_label(step.id, callout_id))
        record = dict(record)
        record.update(suspend_retried=True, deadline=now + limit)
        self._store.note_condition(
            step.id, "callout:%s: timed out across a suspend; restarted once" % callout_id)
        return record

    def _reap_preflight(self, step, callout_id, record, result, now):
        errors = preflight_errors(result, record.get("preflight_timeout"))
        if errors:
            return self._record_failure(step.id, callout_id, record, "", now, errors)
        callout = self._callout(callout_id)
        if callout is None:
            return self._record_failure(
                step.id, callout_id, record, "callout is no longer configured", now)
        presents = self._presents(step)
        record = dict(record)
        record.pop("suspend_retried", None)
        record.update(phase=PHASE_RUN, deadline=now + callout.timeout)
        self._runner.start(
            callout_key(step.id, callout_id), callout.command, self._cwd(step),
            self._config.base_env(), json.dumps(self._request(step, callout, presents, "run")),
            callout.timeout, callout_log_label(step.id, callout_id))
        return record

    def _callout(self, callout_id):
        for callout in self._config.callouts():
            if callout.id == callout_id:
                return callout
        return None

    def _start(self, now):
        callouts = self._config.callouts()
        started = []
        if not callouts:
            return started
        for step in self._store.all_steps():
            if step.state != State.WAITING or step.role != "human":
                continue
            presents = self._presents(step)
            if presents is None:
                continue
            runs = callout_runs_of(self._store, step.id)
            for callout in callouts:
                if callout.subject != presents or callout.id in runs:
                    continue
                key = callout_key(step.id, callout.id, PHASE_PREFLIGHT)
                limit = preflight_timeout(callout.timeout)
                runs[callout.id] = {
                    "status": STATUS_RUNNING, "phase": PHASE_PREFLIGHT, "wait": callout.wait,
                    "started": now, "deadline": now + limit, "timeout": callout.timeout,
                    "preflight_timeout": limit, "message": None, "artifacts": [], "errors": [],
                }
                self._write(step.id, runs)
                try:
                    stdin = json.dumps(self._request(step, callout, presents, "preflight"))
                    self._runner.start(
                        key, callout.command, self._cwd(step), self._config.base_env(), stdin,
                        limit, callout_log_label(step.id, callout.id))
                    started.append(key)
                except _CALLOUT_ERRORS as e:
                    runs[callout.id] = self._record_failure(
                        step.id, callout.id, runs[callout.id], str(e), now)
                    self._write(step.id, runs)
        return started

    def _presents(self, step):
        try:
            if skip_unpinned(self._store, self._flow_service, step):
                return None
            value = flow_for(self._flow_service, step).step_def(step.stage).presents
        except _CALLOUT_ERRORS:
            return None
        return str(value).strip() if value is not None else None

    def _repo_path(self, step):
        repo = self._store.item_fields(step.item).repo
        if not repo:
            return None
        try:
            return ProjectRegistry(self._store).resolve_path(repo)
        except ProjectResolutionError:
            return None

    def _cwd(self, step):
        return self._repo_path(step) or self._config.expand_path("~")

    def _workspace(self, step):
        if not self._worktrees.item_branch(step):
            return None
        return self._worktrees.worktree_path(step)

    def _request(self, step, callout, presents, verb):
        item = self._store.get_item(step.item)
        request = {
            "protocol": PROTOCOL,
            "verb": verb,
            "callout": callout.id,
        }
        if verb == "preflight":
            request["context"] = "gate"
        request["item"] = {
            "id": item.id, "title": item.title, "repo": item.repo, "project": item.project}
        request["step"] = {
            "id": step.id, "stage": step.stage,
            "workflow": self._flow_service.workflow_for(step)}
        if verb == "run":
            request["subject"] = self._subject(step, item, presents)
        request["repos"] = {
            "repo_path": self._repo_path(step), "workspace": self._workspace(step)}
        return request

    def _subject(self, step, item, presents):
        focus = parse_presents(presents)
        if focus.kind == FOCUS_ARTIFACT:
            value = None
            for artifact in self._store.item_artifacts(step.item):
                if artifact.type == focus.name:
                    value = artifact.value
            return {"kind": "artifact", "name": focus.name, "value": value}
        if focus.kind == "description":
            return {"kind": "description", "value": item.description}
        phase = flow_for(self._flow_service, step).step_def(step.stage).phase
        run = self._store.current_run(step.item, phase)
        url = run.pr if run else None
        subject = {"kind": "pr", "url": url, "base": self._base(url)}
        if run is not None and run.stack:
            subject.update(self._stack.read(run.stack))
        else:
            subject["stack_layers"] = []
        return subject

    def _base(self, url):
        if not url:
            return None
        view = self._github.pr_view(url)
        return view.base_ref if isinstance(view, PrView) else None

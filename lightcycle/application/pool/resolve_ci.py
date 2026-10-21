from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
from lightcycle.application.pool.skip_idle_ci_watch import SkipIdleCiWatchUseCase
from lightcycle.domain.pool import MISSING_STATUS, ci_outcome, failing_check, judged_checks, timed_out_check
from lightcycle.domain.work import State
from lightcycle.ports.github import NotYetRead, PrSync, ReadFailure


@dataclass(frozen=True)
class CiUnread:
    step: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ResolveCiResponse:
    ci_resolved: List[str] = field(default_factory=list)
    ci_unread: List[CiUnread] = field(default_factory=list)


def _reason(call, failure):
    kind = "not-yet-read" if isinstance(failure, NotYetRead) else "read-failed"
    return "%s-%s" % (call, kind)


class ResolveCiUseCase:
    def __init__(
        self, store, github, flow_service, complete, *, clock, poll_seconds, ci_ceiling_seconds, wall_clock,
        views, trusted_authors,
    ):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._ci_ceiling_seconds = ci_ceiling_seconds
        self._wall_clock = wall_clock
        self._views = views
        self._skip_idle = SkipIdleCiWatchUseCase(
            store, github, flow_service, complete, trusted_authors=trusted_authors)
        self._unread = {}
        self._first_epoch = {}
        self._first_judged = {}
        ci_ceiling_seconds()

    def _note_unread(self, step, reason, failure, still_unread, ci_unread):
        now = self._clock()
        since, _, logged = self._unread.get(step.id, (now, reason, None))
        still_unread.add(step.id)
        if now - since > self._poll_seconds() and reason != logged:
            logged = reason
            ci_unread.append(CiUnread(step.id, reason, getattr(failure, "stderr", "") or ""))
        self._unread[step.id] = (since, reason, logged)

    def _required(self, pr_value):
        sync = self._github.pr_sync_state(pr_value)
        if not isinstance(sync, PrSync):
            return None
        value = self._github.required_checks(sync.base_key)
        return None if isinstance(value, ReadFailure) else value

    def execute(self) -> ResolveCiResponse:
        ci_resolved = []
        ci_unread = []
        still_unread = set()
        seen = set()
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE or step.role != "engine":
                continue
            if skip_unpinned(self._store, self._flow_service, step):
                continue
            flow = flow_for(self._flow_service, step)
            sd = flow.step_def(step.stage)
            if sd.ci_success is None and sd.ci_failure is None:
                continue
            run = run_of(self._store, self._flow_service, step)
            pr_value = run.pr if run else None
            if not pr_value:
                continue
            epoch = self._first_epoch.setdefault(step.id, self._views.poll_epoch())
            seen.add(step.id)
            if not self._views.confirmed_after(pr_value, epoch):
                held_sha = self._github.head_sha(pr_value)
                if held_sha and not isinstance(held_sha, ReadFailure):
                    self._github.check_runs(pr_value, held_sha)
                self._note_unread(step, "view-not-confirmed", None, still_unread, ci_unread)
                continue
            sha = self._github.head_sha(pr_value)
            if isinstance(sha, ReadFailure):
                self._note_unread(step, _reason("head", sha), sha, still_unread, ci_unread)
                continue
            if not sha:
                continue
            checks = self._github.check_runs(pr_value, sha)
            if isinstance(checks, ReadFailure):
                self._note_unread(step, _reason("checks", checks), checks, still_unread, ci_unread)
                continue
            required = self._required(pr_value)
            ceiling = self._ci_ceiling_seconds()
            now = self._wall_clock()
            judged_sha, since = self._first_judged.get(step.id, (None, now))
            if judged_sha != sha:
                since = now
            self._first_judged[step.id] = (sha, since)
            outcome = ci_outcome(checks, required, now, ceiling, since)
            if outcome == "pending":
                continue
            if outcome == "success" and sd.ci_success:
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                done = self._complete.execute(CompleteInput(
                    step=step.id, outcome=sd.ci_success, note="CI succeeded on %s." % sha,
                ))
                if done.next_step:
                    self._skip_idle.execute(step, done.next_step, pr_value, sha)
                ci_resolved.append(step.item)
            elif outcome == "timeout" and sd.ci_failure:
                if self._github.head_sha(pr_value) != sha:
                    continue
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                hung = timed_out_check(judged_checks(checks, required, since), now, ceiling)
                url = " %s" % hung.url if hung.url else ""
                if hung.status == MISSING_STATUS:
                    note = (
                        "CI timed out on %s: required check '%s' never appeared after %ds, past the "
                        "ceiling of %ds (ci-check-ceiling-seconds), PR %s."
                    ) % (sha, hung.name, int(now - since), ceiling, pr_value)
                else:
                    note = (
                        "CI timed out on %s: check '%s'%s still in progress after %ds, past the "
                        "ceiling of %ds (ci-check-ceiling-seconds), PR %s."
                    ) % (sha, hung.name, url, int(now - hung.started_at), ceiling, pr_value)
                self._complete.execute(CompleteInput(step=step.id, outcome=sd.ci_failure, note=note))
                ci_resolved.append(step.item)
            elif outcome == "failure" and sd.ci_failure:
                if self._github.head_sha(pr_value) != sha:
                    continue
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                fc = failing_check(judged_checks(checks, required, since))
                url = " %s" % fc.url if fc and fc.url else ""
                note = "CI failed on %s: check '%s'%s, PR %s." % (
                    sha, fc.name if fc else "unknown", url, pr_value,
                )
                self._complete.execute(CompleteInput(step=step.id, outcome=sd.ci_failure, note=note))
                ci_resolved.append(step.item)
        for step_id in [k for k in self._unread if k not in still_unread]:
            del self._unread[step_id]
        for step_id in [k for k in self._first_epoch if k not in seen]:
            del self._first_epoch[step_id]
        for step_id in [k for k in self._first_judged if k not in seen]:
            del self._first_judged[step_id]
        return ResolveCiResponse(ci_resolved=ci_resolved, ci_unread=ci_unread)

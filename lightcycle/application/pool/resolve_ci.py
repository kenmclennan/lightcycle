from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
from lightcycle.application.pool.skip_idle_ci_watch import SkipIdleCiWatchUseCase
from lightcycle.domain.pool import (
    MISSING_STATUS, ci_outcome, failing_check, judged_checks, pr_workflows_expected, timed_out_check,
)
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
        self, store, github, flow_service, complete, *, clock, poll_seconds, ci_ceiling_seconds,
        ci_start_window_seconds, ci_no_workflows_wait_seconds, wall_clock, views, trusted_authors,
    ):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._ci_ceiling_seconds = ci_ceiling_seconds
        self._ci_start_window_seconds = ci_start_window_seconds
        self._ci_no_workflows_wait_seconds = ci_no_workflows_wait_seconds
        self._wall_clock = wall_clock
        self._views = views
        self._skip_idle = SkipIdleCiWatchUseCase(
            store, github, flow_service, complete, trusted_authors=trusted_authors)
        self._unread = {}
        self._first_epoch = {}
        self._first_judged = {}
        self._expected = {}
        ci_ceiling_seconds()
        ci_start_window_seconds()
        ci_no_workflows_wait_seconds()

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

    def _expectation(self, step, pr_value, sha, still_unread, ci_unread):
        cached = self._expected.get(step.id)
        if cached and cached[0] == sha:
            return cached[1]
        sources = self._github.workflow_sources(pr_value, sha)
        if isinstance(sources, ReadFailure):
            self._note_unread(step, _reason("workflow-sources", sources), sources, still_unread, ci_unread)
            return None
        files = self._github.changed_files(pr_value, sha)
        if isinstance(files, ReadFailure):
            self._note_unread(step, _reason("changed-files", files), files, still_unread, ci_unread)
            return None
        sync = self._github.pr_sync_state(pr_value)
        if isinstance(sync, ReadFailure):
            self._note_unread(step, _reason("sync", sync), sync, still_unread, ci_unread)
            return None
        base = sync.base_key.partition("@")[2]
        expectation = (pr_workflows_expected(sources, base, files), base)
        self._expected[step.id] = (sha, expectation)
        return expectation

    def _park_stalled(self, step, pr_value, sha, window, base, expectation, elapsed):
        names = ", ".join(expectation.expected)
        unreadable = ", ".join(expectation.unreadable) or "none"
        ParkStepUseCase(self._store).execute(ParkInput(
            step=step.id,
            observation=(
                "No workflow run appeared for %s within %ds (ci-start-window-seconds) although "
                "these workflows should run for base %s: %s. Could not read or parse: %s. PR %s."
            ) % (sha, window, base, names, unreadable, pr_value),
            decision=(
                "Open the PR's Actions tab and find out why nothing started (a merge conflict also "
                "stops pull_request runs). Fix or re-run the workflows, or confirm they do not run "
                "on this PR, then unblock this step; unblocking restarts the wait for a fresh window."
            ),
            tried="Listed workflow runs for the head on every poll for %ds." % elapsed,
        ))

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
            judged = judged_checks(checks, required, since)
            runs = None
            expectation = None
            base = ""
            if not judged:
                runs = self._github.workflow_runs(pr_value, sha)
                if isinstance(runs, ReadFailure):
                    self._note_unread(step, _reason("workflow-runs", runs), runs, still_unread, ci_unread)
                    continue
                if runs == 0:
                    found = self._expectation(step, pr_value, sha, still_unread, ci_unread)
                    if found is None:
                        continue
                    expectation, base = found
            outcome = ci_outcome(
                checks, required, now, ceiling, since, runs=runs,
                expected=expectation.expected if expectation else None,
                start_window=self._ci_start_window_seconds(),
                quiet_wait=self._ci_no_workflows_wait_seconds(),
            )
            if outcome == "pending":
                continue
            if outcome == "stalled":
                if self._github.head_sha(pr_value) != sha:
                    continue
                self._park_stalled(
                    step, pr_value, sha, self._ci_start_window_seconds(), base, expectation,
                    int(now - since),
                )
                self._first_judged.pop(step.id, None)
                self._expected.pop(step.id, None)
                continue
            if outcome == "success" and sd.ci_success:
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                note = "CI succeeded on %s." % sha if judged else (
                    "no CI checks are defined for this repo; none appeared on %s." % sha)
                done = self._complete.execute(CompleteInput(
                    step=step.id, outcome=sd.ci_success, note=note,
                ))
                if done.next_step:
                    self._skip_idle.execute(step, done.next_step, pr_value, sha)
                ci_resolved.append(step.item)
            elif outcome == "timeout" and sd.ci_failure:
                if self._github.head_sha(pr_value) != sha:
                    continue
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                hung = timed_out_check(judged, now, ceiling, since)
                url = " %s" % hung.url if hung and hung.url else ""
                if hung is None:
                    note = (
                        "CI timed out on %s: %d workflow run(s) listed for the head but no check run "
                        "appeared after %ds, past the ceiling of %ds (ci-check-ceiling-seconds), PR %s."
                    ) % (sha, runs, int(now - since), ceiling, pr_value)
                elif hung.status == MISSING_STATUS:
                    note = (
                        "CI timed out on %s: required check '%s' never appeared after %ds, past the "
                        "ceiling of %ds (ci-check-ceiling-seconds), PR %s."
                    ) % (sha, hung.name, int(now - since), ceiling, pr_value)
                else:
                    started = hung.started_at if hung.started_at > 0 else since
                    note = (
                        "CI timed out on %s: check '%s'%s still %s after %ds, past the "
                        "ceiling of %ds (ci-check-ceiling-seconds), PR %s."
                    ) % (sha, hung.name, url, hung.status.replace("_", " "), int(now - started),
                         ceiling, pr_value)
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
        for step_id in [k for k in self._expected if k not in seen]:
            del self._expected[step_id]
        return ResolveCiResponse(ci_resolved=ci_resolved, ci_unread=ci_unread)

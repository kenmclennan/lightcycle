import json
from dataclasses import dataclass, field, replace
from typing import Any, List, Optional

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
from lightcycle.application.pool.skip_idle_ci_watch import SkipIdleCiWatchUseCase
from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.domain.pool import (
    MISSING_STATUS, cancelled_check, check_label, ci_outcome, failing_check, judged_checks, pr_workflows_expected, status_mismatch,
    timed_out_check, unrun_checks,
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


_OWN = object()


@dataclass
class _Pass:
    still_unread: set = field(default_factory=set)
    ci_unread: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    awaited: set = field(default_factory=set)


@dataclass
class _Verdict:
    pr: str
    key: str
    sha: str
    outcome: str
    checks: Any
    judged: Any
    required: Any
    since: float
    now: float
    runs: Optional[int]
    expectation: Any
    base: str
    unrun: tuple = ()


def _reason(call, failure):
    kind = "not-yet-read" if isinstance(failure, NotYetRead) else "read-failed"
    return "%s-%s" % (call, kind)


class ResolveCiUseCase:
    def __init__(
        self, store, github, flow_service, complete, *, clock, poll_seconds, ci_ceiling_seconds,
        ci_start_window_seconds, ci_no_workflows_wait_seconds, wall_clock, views, trusted_authors,
        ci_unconfirmed_note_polls,
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
        self._ci_unconfirmed_note_polls = ci_unconfirmed_note_polls
        self._wall_clock = wall_clock
        self._views = views
        self._skip_idle = SkipIdleCiWatchUseCase(
            store, github, flow_service, complete, trusted_authors=trusted_authors)
        self._unread = {}
        self._noted = {}
        self._first_epoch = {}
        self._first_judged = {}
        self._expected = {}
        self._mismatch_noted = set()
        ci_ceiling_seconds()
        ci_start_window_seconds()
        ci_no_workflows_wait_seconds()
        ci_unconfirmed_note_polls()

    def _note_unread(self, step, reason, failure, still_unread, ci_unread, key=None):
        key = key or step.id
        now = self._clock()
        since, _, logged = self._unread.get(key, (now, reason, None))
        still_unread.add(key)
        if now - since > self._poll_seconds() and reason != logged:
            logged = reason
            ci_unread.append(CiUnread(step.id, reason, getattr(failure, "stderr", "") or ""))
        self._unread[key] = (since, reason, logged)

    def _note_unconfirmed(self, step, pr_value, key):
        now = self._clock()
        since = self._unread[key][0]
        interval = self._ci_unconfirmed_note_polls() * self._poll_seconds()
        last = self._noted.get(key, since)
        if now - last <= interval:
            return
        self._noted[key] = now
        self._store.note_condition(
            step.id,
            "poll-ci is waiting for a GitHub poll to confirm %s; no poll has confirmed it for more "
            "than %d poll intervals (ci-unconfirmed-note-polls)"
            % (pr_value, self._ci_unconfirmed_note_polls()),
        )

    def _note_mismatch(self, step, judged, key):
        if key in self._mismatch_noted:
            return
        odd = next((c for c in judged if status_mismatch(c)), None)
        if odd is None:
            return
        self._mismatch_noted.add(key)
        self._store.note_condition(
            step.id,
            "poll-ci is holding check '%s' pending: GitHub reports it completed with no conclusion"
            % check_label(odd),
        )

    def _required(self, pr_value):
        sync = self._github.pr_sync_state(pr_value)
        if not isinstance(sync, PrSync):
            return None
        value = self._github.required_checks(sync.base_key)
        return None if isinstance(value, ReadFailure) else value

    def _expectation(self, step, pr_value, sha, still_unread, ci_unread, key):
        cached = self._expected.get(key)
        if cached and cached[0] == sha:
            return cached[1]
        sources = self._github.workflow_sources(pr_value, sha)
        if isinstance(sources, ReadFailure):
            self._note_unread(step, _reason("workflow-sources", sources), sources, still_unread, ci_unread, key)
            return None
        files = self._github.changed_files(pr_value, sha)
        if isinstance(files, ReadFailure):
            self._note_unread(step, _reason("changed-files", files), files, still_unread, ci_unread, key)
            return None
        sync = self._github.pr_sync_state(pr_value)
        if isinstance(sync, ReadFailure):
            self._note_unread(step, _reason("sync", sync), sync, still_unread, ci_unread, key)
            return None
        base = sync.base_key.partition("@")[2]
        expectation = (pr_workflows_expected(sources, base, files), base)
        self._expected[key] = (sha, expectation)
        return expectation

    def _park_stalled(self, step, where, sha, window, base, expectation, elapsed):
        names = ", ".join(expectation.expected)
        unreadable = ", ".join(expectation.unreadable) or "none"
        ParkStepUseCase(self._store).execute(ParkInput(
            step=step.id,
            observation=(
                "No workflow run appeared for %s within %ds (ci-start-window-seconds) although "
                "these workflows should run for base %s: %s. Could not read or parse: %s. %s."
            ) % (sha, window, base, names, unreadable, where),
            decision=(
                "Open the PR's Actions tab and find out why nothing started (a merge conflict also "
                "stops pull_request runs). Fix or re-run the workflows, or confirm they do not run "
                "on this PR, then unblock this step; unblocking restarts the wait for a fresh window."
            ),
            tried="Listed workflow runs for the head on every poll for %ds." % elapsed,
        ))

    def _park_cancelled(self, step, where, sha, check):
        url = " (%s)" % check.url if check.url else ""
        ParkStepUseCase(self._store).execute(ParkInput(
            step=step.id,
            observation=(
                "Check '%s'%s was cancelled on %s, %s, and no other check failed; no test "
                "failed, so no code change is called for."
            ) % (check_label(check), url, sha, where),
            decision=(
                "Rerun the cancelled job, then unblock this step; unblocking restarts the wait "
                "for a fresh result."
            ),
            tried="Judged every check on the head; none failed and the cancelled one is not a failure.",
        ))

    def _already_closed(self, step):
        return self._store.get_node(step.id).state == State.DONE

    def _judge(self, step, pr_value, key, required, ctx):
        epoch = self._first_epoch.setdefault(key, self._views.poll_epoch())
        ctx.seen.add(key)
        ctx.awaited.add(pr_value)
        if not self._views.confirmed_after(pr_value, epoch):
            held_sha = self._github.head_sha(pr_value)
            if held_sha and not isinstance(held_sha, ReadFailure):
                self._github.check_runs(pr_value, held_sha)
            self._note_unread(step, "view-not-confirmed", None, ctx.still_unread, ctx.ci_unread, key)
            self._note_unconfirmed(step, pr_value, key)
            return None
        sha = self._github.head_sha(pr_value)
        if isinstance(sha, ReadFailure):
            self._note_unread(step, _reason("head", sha), sha, ctx.still_unread, ctx.ci_unread, key)
            return None
        if not sha:
            return None
        checks = self._github.check_runs(pr_value, sha)
        if isinstance(checks, ReadFailure):
            self._note_unread(
                step, _reason("checks", checks), checks, ctx.still_unread, ctx.ci_unread, key)
            return None
        if required is _OWN:
            required = self._required(pr_value)
        ceiling = self._ci_ceiling_seconds()
        now = self._wall_clock()
        judged_sha, since = self._first_judged.get(key, (None, now))
        if judged_sha != sha:
            since = now
        self._first_judged[key] = (sha, since)
        judged = judged_checks(checks, required, since)
        self._note_mismatch(step, judged, key)
        runs = None
        expectation = None
        base = ""
        if not judged:
            runs = self._github.workflow_runs(pr_value, sha)
            if isinstance(runs, ReadFailure):
                self._note_unread(
                    step, _reason("workflow-runs", runs), runs, ctx.still_unread, ctx.ci_unread, key)
                return None
            if runs == 0:
                found = self._expectation(
                    step, pr_value, sha, ctx.still_unread, ctx.ci_unread, key)
                if found is None:
                    return None
                expectation, base = found
        outcome = ci_outcome(
            checks, required, now, ceiling, since, runs=runs,
            expected=expectation.expected if expectation else None,
            start_window=self._ci_start_window_seconds(),
            quiet_wait=self._ci_no_workflows_wait_seconds(),
        )
        return _Verdict(
            pr_value, key, sha, outcome, checks, judged, required, since, now, runs, expectation,
            base,
        )

    def _head_still(self, v):
        return self._github.head_sha(v.pr) == v.sha

    def _park_for(self, step, v, where):
        if v.outcome == "stalled":
            if not self._head_still(v):
                return False
            self._park_stalled(
                step, where, v.sha, self._ci_start_window_seconds(), v.base, v.expectation,
                int(v.now - v.since),
            )
            self._first_judged.pop(v.key, None)
            self._expected.pop(v.key, None)
            return True
        if not self._head_still(v):
            return False
        self._park_cancelled(
            step, where, v.sha, cancelled_check(judged_checks(v.checks, v.required, v.since)))
        self._first_judged.pop(v.key, None)
        return True

    def _timeout_note(self, v, where):
        ceiling = self._ci_ceiling_seconds()
        hung = timed_out_check(v.judged, v.now, ceiling, v.since)
        url = " %s" % hung.url if hung and hung.url else ""
        if hung is None:
            return (
                "CI timed out on %s: %d workflow run(s) listed for the head but no check run "
                "appeared after %ds, past the ceiling of %ds (ci-check-ceiling-seconds), %s."
            ) % (v.sha, v.runs, int(v.now - v.since), ceiling, where)
        if hung.status == MISSING_STATUS:
            return (
                "CI timed out on %s: required check '%s' never appeared after %ds, past the "
                "ceiling of %ds (ci-check-ceiling-seconds), %s."
            ) % (v.sha, hung.name, int(v.now - v.since), ceiling, where)
        started = hung.started_at if hung.started_at > 0 else v.since
        return (
            "CI timed out on %s: check '%s'%s still %s after %ds, past the "
            "ceiling of %ds (ci-check-ceiling-seconds), %s."
        ) % (v.sha, check_label(hung), url, hung.status.replace("_", " "), int(v.now - started),
             ceiling, where)

    def _failure_note(self, v, where):
        fc = failing_check(judged_checks(v.checks, v.required, v.since))
        url = " %s" % fc.url if fc and fc.url else ""
        return "CI failed on %s: check '%s'%s, %s." % (
            v.sha, check_label(fc) if fc else "unknown", url, where)

    def _record_judged(self, step, verdicts):
        self._store.add_artifact(step.id, "ci-judged-sha", verdicts[-1].sha, internal=True)
        self._store.add_artifact(
            step.id, "ci-judged-layers",
            json.dumps({v.pr: v.sha for v in verdicts}, sort_keys=True), internal=True)

    def _finish_unstacked(self, step, sd, v, ci_resolved):
        where = "PR %s" % v.pr
        if v.outcome == "pending":
            return
        if v.outcome in ("stalled", "cancelled"):
            self._park_for(step, v, where)
            return
        if v.outcome == "success" and sd.ci_success:
            self._store.add_artifact(step.id, "ci-judged-sha", v.sha, internal=True)
            note = "CI succeeded on %s." % v.sha if v.judged else (
                "no CI checks are defined for this repo; none appeared on %s." % v.sha)
            if self._already_closed(step):
                return
            done = self._complete.execute(CompleteInput(
                step=step.id, outcome=sd.ci_success, note=note,
            ))
            if done.next_step:
                self._skip_idle.execute(step, done.next_step, v.pr, v.sha)
            ci_resolved.append(step.item)
        elif v.outcome == "timeout" and sd.ci_failure:
            if not self._head_still(v):
                return
            self._store.add_artifact(step.id, "ci-judged-sha", v.sha, internal=True)
            note = self._timeout_note(v, where)
            if self._already_closed(step):
                return
            self._complete.execute(CompleteInput(step=step.id, outcome=sd.ci_failure, note=note))
            ci_resolved.append(step.item)
        elif v.outcome == "failure" and sd.ci_failure:
            if not self._head_still(v):
                return
            self._store.add_artifact(step.id, "ci-judged-sha", v.sha, internal=True)
            note = self._failure_note(v, where)
            if self._already_closed(step):
                return
            self._complete.execute(CompleteInput(step=step.id, outcome=sd.ci_failure, note=note))
            ci_resolved.append(step.item)

    def _finish_stacked(self, step, sd, labelled, ci_resolved):
        verdicts = [v for _, v in labelled if v is not None]
        for name, v in labelled:
            if v is None:
                continue
            where = "%s (PR %s)" % (name, v.pr)
            if v.outcome in ("failure", "timeout") and sd.ci_failure:
                if not self._head_still(v):
                    return
                self._record_judged(step, verdicts)
                note = (self._failure_note(v, where) if v.outcome == "failure"
                        else self._timeout_note(v, where))
                if self._already_closed(step):
                    return
                self._complete.execute(
                    CompleteInput(step=step.id, outcome=sd.ci_failure, note=note))
                ci_resolved.append(step.item)
                return
        for name, v in labelled:
            if v is not None and v.outcome in ("cancelled", "stalled"):
                self._park_for(step, v, "%s (PR %s)" % (name, v.pr))
                return
        if len(verdicts) != len(labelled) or any(v.outcome != "success" for v in verdicts):
            return
        if not sd.ci_success or not all(self._head_still(v) for v in verdicts):
            return
        self._record_judged(step, verdicts)
        note = "CI succeeded on %s." % "; ".join(
            "%s (%s) %s" % (name, v.pr, v.sha) for name, v in labelled)
        unrun = [(name, v) for name, v in labelled if v.unrun]
        if unrun:
            note += " " + " ".join(
                "CI not run on %s (%s): %s." % (name, v.pr, ", ".join(v.unrun)) for name, v in unrun)
            self._store.add_artifact(
                step.id, "ci-not-run",
                "\n".join("%s %s: %s" % (name, v.pr, ", ".join(v.unrun)) for name, v in unrun))
        if self._already_closed(step):
            return
        self._complete.execute(CompleteInput(step=step.id, outcome=sd.ci_success, note=note))
        ci_resolved.append(step.item)

    def _mark_unrun(self, labelled, required):
        bottom = labelled[0][1]
        if bottom is None:
            return labelled
        expected = {
            check_label(c) for c in bottom.checks if required is None or c.name not in required}
        window = self._ci_start_window_seconds()
        marked = [labelled[0]]
        for name, v in labelled[1:]:
            if v is not None and v.outcome == "success":
                unrun = unrun_checks(expected, v.checks)
                if unrun:
                    if window is not None and v.now - v.since > window:
                        v = replace(v, unrun=unrun)
                    else:
                        v = replace(v, outcome="pending")
            marked.append((name, v))
        return marked

    def _judge_stack(self, step, sd, run, ctx, ci_resolved):
        stack = read_stack(self._github, run.stack)
        ctx.awaited.add(run.pr)
        if not stack.layers:
            return
        if any(layer.state == "closed" for layer in stack.layers):
            return
        total = len(stack.layers)
        open_layers = [
            (position, layer) for position, layer in enumerate(stack.layers, start=1)
            if layer.state == "open"
        ]
        if not open_layers:
            return
        required = self._required(open_layers[0][1].url)
        labelled = []
        for position, layer in open_layers:
            key = "%s@%s" % (step.id, layer.url)
            v = self._judge(step, layer.url, key, required, ctx)
            labelled.append(("layer %d of %d" % (position, total), v))
        labelled = self._mark_unrun(labelled, required)
        self._finish_stacked(step, sd, labelled, ci_resolved)

    def execute(self) -> ResolveCiResponse:
        ci_resolved = []
        ctx = _Pass()
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
            if run.stack:
                self._judge_stack(step, sd, run, ctx, ci_resolved)
                continue
            v = self._judge(step, pr_value, step.id, _OWN, ctx)
            if v is not None:
                self._finish_unstacked(step, sd, v, ci_resolved)
        for key in [k for k in self._unread if k not in ctx.still_unread]:
            del self._unread[key]
        for key in [k for k in self._noted if k not in ctx.still_unread]:
            del self._noted[key]
        self._views.hold_prs(ctx.awaited)
        for key in [k for k in self._first_epoch if k not in ctx.seen]:
            del self._first_epoch[key]
        for key in [k for k in self._first_judged if k not in ctx.seen]:
            del self._first_judged[key]
        for key in [k for k in self._expected if k not in ctx.seen]:
            del self._expected[key]
        self._mismatch_noted &= ctx.seen
        return ResolveCiResponse(ci_resolved=ci_resolved, ci_unread=ctx.ci_unread)

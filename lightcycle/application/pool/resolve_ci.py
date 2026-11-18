import json
from dataclasses import dataclass, field, replace
from typing import Any, List, Optional

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.pool.pr_lookups import (
    flow_for, latest_artifact, latest_judged_artifact, run_of, skip_unpinned,
)
from lightcycle.application.pool.skip_idle_ci_watch import SkipIdleCiWatchUseCase
from lightcycle.application.pool.stack_reads import read_stack, record_final_stack
from lightcycle.application.work.gate_hold import GateHold, route_name
from lightcycle.application.work.close_item import (
    CloseItemInput, TeardownRefused,
)
from lightcycle.domain.pool import stack_shape
from lightcycle.domain.pool import (
    MISSING_STATUS, cancelled_check, check_label, ci_outcome, failing_check, judged_checks, pr_workflows_expected, status_mismatch,
    timed_out_check, unrun_checks,
)
from lightcycle.domain.pool.sleep import awake_elapsed
from lightcycle.domain.work import State
from lightcycle.domain.work.layer_ci_wait import (
    LAYER_CI_MERGED, LAYER_CI_MOVED, LAYER_CI_WAIT, MERGE_NEXT,
)
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
    sleeps: tuple = ()


def _cancelled_identities(judged):
    return frozenset(
        (check_label(c), c.url, c.completed_at) for c in judged if c.conclusion == "cancelled")


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
    sleeps: tuple = ()


def _reason(call, failure):
    kind = "not-yet-read" if isinstance(failure, NotYetRead) else "read-failed"
    return "%s-%s" % (call, kind)


class ResolveCiUseCase:
    def __init__(
        self, store, github, flow_service, complete, *, close_item, clock, poll_seconds, ci_ceiling_seconds,
        ci_start_window_seconds, ci_no_workflows_wait_seconds, wall_clock, views, trusted_authors,
        ci_unconfirmed_note_polls,
    ):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._close_item = close_item
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
        self._unread_run = {}
        self._noted = {}
        self._first_epoch = {}
        self._first_judged = {}
        self._cancel_parked = {}
        self._lagging = {}
        self._expected = {}
        self._stack_expected = {}
        self._retarget_since = {}
        self._gate_hold = GateHold(store)
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
        self._unread[key] = (since, reason, logged)
        run_reason, run_since = self._unread_run.get(key, (reason, now))
        if run_reason != reason:
            run_since = now
        self._unread_run[key] = (reason, run_since)
        if now - run_since > self._ci_ceiling_seconds() and self._store.get_node(step.id).role == "engine":
            self._park_unread(step, key, reason, failure, int(now - run_since))
            self._unread_run.pop(key, None)
            return
        if now - since > self._poll_seconds() and reason != logged:
            logged = reason
            ci_unread.append(CiUnread(step.id, reason, getattr(failure, "stderr", "") or ""))
        self._unread[key] = (since, reason, logged)

    def _park_unread(self, step, key, reason, failure, elapsed):
        if "@" in key:
            pr_value = key.partition("@")[2]
        else:
            pr_value = run_of(self._store, self._flow_service, step).pr
        text = getattr(failure, "stderr", "") or "none reported"
        ParkStepUseCase(self._store).execute(ParkInput(
            step=step.id,
            observation=(
                "poll-ci could not read GitHub for PR %s: %s has failed for %ds, past the ceiling of "
                "%ds (ci-check-ceiling-seconds). Last error: %s."
            ) % (pr_value, reason, elapsed, self._ci_ceiling_seconds(), text),
            decision=(
                "Find out why GitHub cannot be read - for example run gh auth status and check the token "
                "has the scopes the poll needs (the rules read needs the repository administration or "
                "rules scope) - fix it, then unblock this step. Unblocking restarts the wait for a fresh ceiling."
            ),
            tried="Re-read on every poll for %ds." % elapsed,
        ))

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
            return None, _reason("sync", sync), sync
        value = self._github.required_checks(sync.base_key)
        if isinstance(value, ReadFailure):
            return None, _reason("rules", value), value
        return value, None, None

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
                "Rerun the cancelled job, then unblock this step; unblocking waits up to the CI check ceiling "
                "for a newer result and parks again only if the same cancelled result is still the latest."
            ),
            tried="Judged every check on the head; none failed and the cancelled one is not a failure.",
        ))

    def _park_head_lag(self, step, pr_value, head, branch, elapsed):
        ParkStepUseCase(self._store).execute(ParkInput(
            step=step.id,
            observation=(
                "The head of PR %s has stayed at %s while its branch is at %s for %ds "
                "(ci-start-window-seconds), so CI has not been judged."
            ) % (pr_value, head, branch, elapsed),
            decision=(
                "Check why GitHub has not moved the PR head to the branch (a push that did not "
                "reach the PR, a closed or reopened PR), then unblock this step; unblocking "
                "restarts the wait for a fresh window."
            ),
            tried="Compared the PR head with its branch ref on every poll for %ds." % elapsed,
        ))

    def _hold_for_lag(self, step, pr_value, key, head, ctx):
        now = self._clock()
        since, noted = self._lagging.get(key, (now, False))
        branch = self._github.pr_view(pr_value)
        branch_sha = getattr(branch, "branch_sha", "")
        window = self._ci_start_window_seconds()
        if window is not None and now - since > window:
            self._lagging.pop(key, None)
            if self._store.get_node(step.id).role == "engine":
                self._park_head_lag(step, pr_value, head, branch_sha, int(now - since))
            return
        if not noted:
            self._store.note_condition(
                step.id,
                "poll-ci is holding CI for %s: the PR head is %s but its branch is at %s"
                % (pr_value, head, branch_sha),
            )
        self._lagging[key] = (since, True)

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
        lag = self._github.head_lags_branch(pr_value)
        if isinstance(lag, (ReadFailure, NotYetRead)):
            self._note_unread(step, _reason("head-lag", lag), lag, ctx.still_unread, ctx.ci_unread, key)
            return None
        if lag:
            self._hold_for_lag(step, pr_value, key, sha, ctx)
            return None
        self._lagging.pop(key, None)
        checks = self._github.check_runs(pr_value, sha)
        if isinstance(checks, ReadFailure):
            self._note_unread(
                step, _reason("checks", checks), checks, ctx.still_unread, ctx.ci_unread, key)
            return None
        if required is _OWN:
            required, reason, failure = self._required(pr_value)
            if reason is not None:
                self._note_unread(step, reason, failure, ctx.still_unread, ctx.ci_unread, key)
                return None
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
            checks, required, now, ceiling, since, runs=runs, sleeps=ctx.sleeps,
            expected=expectation.expected if expectation else None,
            start_window=self._ci_start_window_seconds(),
            quiet_wait=self._ci_no_workflows_wait_seconds(),
        )
        outcome = self._hold_stale_cancel(key, sha, outcome, judged, now, ceiling, since, ctx)
        return _Verdict(
            pr_value, key, sha, outcome, checks, judged, required, since, now, runs, expectation,
            base, sleeps=ctx.sleeps,
        )

    def _hold_stale_cancel(self, key, sha, outcome, judged, now, ceiling, since, ctx):
        entry = self._cancel_parked.get(key)
        if entry is None:
            return outcome
        if entry[0] != sha:
            del self._cancel_parked[key]
            return outcome
        if outcome != "cancelled":
            return outcome
        if awake_elapsed(since, now, ctx.sleeps) > ceiling:
            return outcome
        current = _cancelled_identities(judged)
        if current and current <= entry[1]:
            return "pending"
        return outcome

    def _head_still(self, v):
        return self._github.head_sha(v.pr) == v.sha

    def _park_for(self, step, v, where):
        if v.outcome == "stalled":
            if not self._head_still(v):
                return False
            self._park_stalled(
                step, where, v.sha, self._ci_start_window_seconds(), v.base, v.expectation,
                int(awake_elapsed(v.since, v.now, v.sleeps)),
            )
            self._first_judged.pop(v.key, None)
            self._expected.pop(v.key, None)
            return True
        if not self._head_still(v):
            return False
        judged = judged_checks(v.checks, v.required, v.since)
        self._park_cancelled(step, where, v.sha, cancelled_check(judged))
        self._cancel_parked[v.key] = (v.sha, _cancelled_identities(judged))
        self._first_judged.pop(v.key, None)
        return True

    def _timeout_note(self, v, where):
        ceiling = self._ci_ceiling_seconds()
        hung = timed_out_check(v.judged, v.now, ceiling, v.since, v.sleeps)
        url = " %s" % hung.url if hung and hung.url else ""
        if hung is None:
            return (
                "CI timed out on %s: %d workflow run(s) listed for the head but no check run "
                "appeared after %ds, past the ceiling of %ds (ci-check-ceiling-seconds), %s."
            ) % (v.sha, v.runs, int(awake_elapsed(v.since, v.now, v.sleeps)), ceiling, where)
        if hung.status == MISSING_STATUS:
            return (
                "CI timed out on %s: required check '%s' never appeared after %ds, past the "
                "ceiling of %ds (ci-check-ceiling-seconds), %s."
            ) % (v.sha, hung.name, int(awake_elapsed(v.since, v.now, v.sleeps)), ceiling, where)
        started = hung.started_at if hung.started_at > 0 else v.since
        return (
            "CI timed out on %s: check '%s'%s still %s after %ds, past the "
            "ceiling of %ds (ci-check-ceiling-seconds), %s."
        ) % (v.sha, check_label(hung), url, hung.status.replace("_", " "), int(awake_elapsed(started, v.now, v.sleeps)),
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

    def _stack_expectation(self, step, v, bottom_pr, ctx):
        cached = self._stack_expected.get(v.key)
        bottom_sync = self._github.pr_sync_state(bottom_pr)
        if isinstance(bottom_sync, ReadFailure):
            self._note_unread(step, _reason("sync", bottom_sync), bottom_sync, ctx.still_unread, ctx.ci_unread, v.key)
            return None
        bottom_base = bottom_sync.base_key.partition("@")[2]
        if cached and cached[0] == v.sha and cached[1] == bottom_base:
            return cached[2]
        sources = self._github.workflow_sources(v.pr, v.sha)
        if isinstance(sources, ReadFailure):
            self._note_unread(
                step, _reason("workflow-sources", sources), sources, ctx.still_unread, ctx.ci_unread, v.key)
            return None
        files = self._github.changed_files(v.pr, v.sha)
        if isinstance(files, ReadFailure):
            self._note_unread(
                step, _reason("changed-files", files), files, ctx.still_unread, ctx.ci_unread, v.key)
            return None
        expectation = pr_workflows_expected(sources, bottom_base, files)
        self._stack_expected[v.key] = (v.sha, bottom_base, expectation)
        return expectation

    def _mark_unrun(self, step, labelled, ctx):
        bottom = labelled[0][1]
        if bottom is None:
            return labelled
        required = bottom.required
        files_by_label = {}
        required_labels = set()
        for c in bottom.checks:
            label = check_label(c)
            if files_by_label.get(label, "") == "":
                files_by_label[label] = c.workflow_file
            if required is not None and c.name in required:
                required_labels.add(label)
        expected = set(files_by_label)
        window = self._ci_start_window_seconds()
        marked = [labelled[0]]
        for name, v in labelled[1:]:
            if v is not None and v.outcome == "success":
                unrun = unrun_checks(expected, v.checks)
                required_unrun = tuple(label for label in unrun if label in required_labels)
                other_unrun = tuple(label for label in unrun if label not in required_labels)
                if other_unrun:
                    expectation = self._stack_expectation(step, v, bottom.pr, ctx)
                    if expectation is None:
                        v = replace(v, outcome="pending")
                        marked.append((name, v))
                        continue
                    other_unrun = tuple(
                        label for label in other_unrun
                        if not files_by_label[label] or files_by_label[label] in expectation.expected)
                unrun = other_unrun + tuple(
                    "%s (required by the base branch)" % label for label in required_unrun)
                if unrun:
                    if window is not None and awake_elapsed(v.since, v.now, v.sleeps) > window:
                        v = replace(v, unrun=unrun)
                    else:
                        v = replace(v, outcome="pending")
            marked.append((name, v))
        return marked

    def _settle_without_open_layer(self, step, run, stack):
        closed = [
            stack_shape.label(position, len(stack.layers), layer.url)
            for position, layer in enumerate(stack.layers, start=1)
            if layer.state == "closed"
        ]
        if closed:
            ParkStepUseCase(self._store).execute_once(
                ParkInput(
                    step=step.id,
                    observation="no layer is open and %s closed without merging" % ", ".join(closed),
                    decision=(
                        "reopen each closed layer with `gh pr reopen <url>`, or abandon the item"
                    ),
                )
            )
            return
        if stack_shape.merge_blocker(stack.layers, run.pr) is not None:
            return
        flow = flow_for(self._flow_service, step)
        outcome = self._merge_outcome(flow, flow.step_def(step.stage).phase)
        if outcome is None:
            return
        disposition = flow.disposition_for(outcome)
        if disposition is None:
            ParkStepUseCase(self._store).execute_once(
                ParkInput(
                    step=step.id,
                    observation=(
                        "every layer merged, but the workflow does not declare a disposition "
                        "for outcome '%s'" % outcome
                    ),
                    decision=(
                        "declare 'disposition: %s completed' in the workflow bundle" % outcome
                    ),
                )
            )
            return
        record_final_stack(self._store, run, stack)
        merged_prs = frozenset([run.pr] + [layer.url for layer in stack.layers])
        try:
            self._close_item.execute(
                CloseItemInput(
                    item=step.item, reason=outcome, disposition=disposition, merged_prs=merged_prs
                )
            )
        except TeardownRefused:
            return

    @staticmethod
    def _merge_outcome(flow, phase):
        for stage in flow.merge_stages():
            sd = flow.step_def(stage)
            if sd.phase == phase and sd.pr_merge:
                return sd.pr_merge
        return None

    def _judge_stack(self, step, sd, run, ctx, ci_resolved):
        stack = read_stack(self._github, run.stack)
        ctx.awaited.add(run.pr)
        if not stack.layers:
            return
        total = len(stack.layers)
        open_layers = [
            (position, layer) for position, layer in enumerate(stack.layers, start=1)
            if layer.state == "open"
        ]
        if not open_layers:
            self._settle_without_open_layer(step, run, stack)
            return
        if any(layer.state == "closed" for layer in stack.layers):
            return
        labelled = []
        for position, layer in open_layers:
            key = "%s@%s" % (step.id, layer.url)
            v = self._judge(step, layer.url, key, _OWN, ctx)
            if self._store.get_node(step.id).role != "engine":
                return
            labelled.append(("layer %d of %d" % (position, total), v))
        labelled = self._mark_unrun(step, labelled, ctx)
        if self._store.get_node(step.id).role != "engine":
            return
        self._finish_stacked(step, sd, labelled, ci_resolved)

    def _set_if_changed(self, step, atype, value):
        if latest_artifact(self._store, step.id, atype) != value:
            self._store.replace_artifact(step.id, atype, value, internal=True)

    def _clear(self, step, *types):
        present = {a.type for a in self._store.item_artifacts(step.id)}
        for atype in types:
            if atype in present:
                self._store.remove_artifact(step.id, atype)

    @staticmethod
    def _decode_map(text):
        try:
            value = json.loads(text) if text else None
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _decode_count(text):
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    def _watch_gate_layers(self, ctx):
        for step in self._store.all_nodes():
            if step.type != "step" or step.state != State.WAITING or step.role != "human":
                continue
            if step.park.needs or skip_unpinned(self._store, self._flow_service, step):
                continue
            flow = flow_for(self._flow_service, step)
            sd = flow.step_def(step.stage)
            if sd.pr_merge is None:
                continue
            run = run_of(self._store, self._flow_service, step)
            if run is None or not run.stack:
                continue
            self._watch_gate(step, flow, sd, run, ctx)

    def _watch_gate(self, step, flow, sd, run, ctx):
        stack = read_stack(self._github, run.stack)
        if not stack.layers or any(layer.state == "closed" for layer in stack.layers):
            return
        held = self._gate_hold.is_held(step.id)
        total = len(stack.layers)
        open_layers = [
            (position, layer) for position, layer in enumerate(stack.layers, start=1)
            if layer.state == "open"
        ]
        if not open_layers:
            if not held:
                self._clear(step, LAYER_CI_WAIT, LAYER_CI_MOVED)
            return
        merged_now = sum(1 for layer in stack.layers if layer.state == "merged")
        recorded_text = latest_artifact(self._store, step.id, LAYER_CI_MERGED)
        recorded = self._decode_count(recorded_text)
        keys_text = latest_judged_artifact(self._store, flow, step, "ci-judged-layers")
        keys = self._decode_map(keys_text) if keys_text is not None else None
        merge_trigger = False
        if recorded is None and keys is None:
            if merged_now > 0 and not held:
                self._set_if_changed(step, LAYER_CI_MERGED, str(merged_now))
        else:
            derived = total - len(keys) if keys else 0
            merge_trigger = merged_now > max(recorded or 0, derived)
        open_urls = {layer.url for _, layer in open_layers}
        moved = self._decode_map(latest_artifact(self._store, step.id, LAYER_CI_MOVED))
        live_moved = {url: head for url, head in moved.items() if url in open_urls}
        if live_moved != moved and not held:
            if live_moved:
                self._set_if_changed(
                    step, LAYER_CI_MOVED, json.dumps(live_moved, sort_keys=True))
            else:
                self._clear(step, LAYER_CI_MOVED)
        target = None
        if merge_trigger:
            target = open_layers[0]
        else:
            target = next(((p, l) for p, l in open_layers if l.url in live_moved), None)
        if target is None:
            if not held:
                self._clear(step, LAYER_CI_WAIT)
                self._set_if_changed(
                    step, MERGE_NEXT, stack_shape.label(open_layers[0][0], total, open_layers[0][1].url))
            return
        position, layer = target
        name = stack_shape.label(position, total, layer.url)
        if not held:
            self._set_if_changed(step, LAYER_CI_WAIT, name)
            self._clear(step, MERGE_NEXT)
        if merge_trigger and not self._retargeted(step, stack, layer, name, held, ctx):
            return
        v = self._judge(step, layer.url, "%s@%s" % (step.id, layer.url), _OWN, ctx)
        if v is None or v.outcome == "pending":
            return
        where = "%s, after %s" % (
            name, "its retarget" if merge_trigger else "its head moved")
        if v.outcome in ("failure", "timeout"):
            if not self._head_still(v):
                return
            note = (self._failure_note(v, where) if v.outcome == "failure"
                    else self._timeout_note(v, where))
            self._fail_gate(step, flow, sd, name, note, held)
            return
        if v.outcome in ("stalled", "cancelled"):
            if not held:
                self._park_for(step, v, where)
            return
        if v.outcome != "success" or held or not self._head_still(v):
            return
        if merge_trigger:
            self._set_if_changed(step, LAYER_CI_MERGED, str(merged_now))
        live_moved.pop(layer.url, None)
        if live_moved:
            self._set_if_changed(step, LAYER_CI_MOVED, json.dumps(live_moved, sort_keys=True))
        else:
            self._clear(step, LAYER_CI_MOVED)
        self._clear(step, LAYER_CI_WAIT)
        self._set_if_changed(
            step, MERGE_NEXT, stack_shape.label(open_layers[0][0], total, open_layers[0][1].url))

    def _retargeted(self, step, stack, layer, name, held, ctx):
        key = "retarget@%s@%s" % (step.id, layer.url)
        ctx.seen.add(key)
        sync = self._github.pr_sync_state(layer.url)
        if not isinstance(sync, PrSync):
            return False
        base = sync.base_key.partition("@")[2]
        if base not in {l.head_ref for l in stack.layers}:
            self._retarget_since.pop(key, None)
            return True
        now = self._clock()
        since = self._retarget_since.setdefault(key, now)
        window = self._ci_start_window_seconds()
        if held or window is None or now - since <= window:
            return False
        ParkStepUseCase(self._store).execute_once(ParkInput(
            step=step.id,
            observation=(
                "%s is still based on %s after the window; GitHub has not retargeted it "
                "onto the trunk" % (name, base)),
            decision=(
                "retarget the layer onto the default branch on GitHub, then unblock this step"),
        ))
        return False

    def _fail_gate(self, step, flow, sd, name, note, held):
        if held:
            route = route_name(flow, step, sd.pr_head_moved) if sd.pr_head_moved else "a park"
            self._gate_hold.observe(
                step, "layer CI failed on %s (would route to %s)" % (name, route))
            return
        if self._already_closed(step):
            return
        if sd.pr_head_moved:
            self._clear(step, LAYER_CI_WAIT, LAYER_CI_MOVED)
            self._complete.execute(CompleteInput(
                step=step.id, outcome=sd.pr_head_moved, note=note))
            return
        ParkStepUseCase(self._store).execute_once(ParkInput(
            step=step.id, observation=note,
            decision="fix or re-run the check, then unblock this step",
        ))

    def execute(self, sleeps=()) -> ResolveCiResponse:
        ci_resolved = []
        ctx = _Pass(sleeps=tuple(sleeps))
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
        self._watch_gate_layers(ctx)
        for key in [k for k in self._unread if k not in ctx.still_unread]:
            del self._unread[key]
        for key in [k for k in self._unread_run if k not in ctx.still_unread]:
            del self._unread_run[key]
        for key in [k for k in self._noted if k not in ctx.still_unread]:
            del self._noted[key]
        self._views.hold_prs(ctx.awaited)
        for key in [k for k in self._first_epoch if k not in ctx.seen]:
            del self._first_epoch[key]
        for key in [k for k in self._first_judged if k not in ctx.seen]:
            del self._first_judged[key]
        for key in [k for k in self._lagging if k not in ctx.seen]:
            del self._lagging[key]
        for key in [k for k in self._expected if k not in ctx.seen]:
            del self._expected[key]
        for key in [k for k in self._stack_expected if k not in ctx.seen]:
            del self._stack_expected[key]
        for key in list(self._cancel_parked):
            node = self._store.get_node(key.split("@")[0])
            if node is None or node.state == State.DONE:
                del self._cancel_parked[key]
        for key in [k for k in self._retarget_since if k not in ctx.seen]:
            del self._retarget_since[key]
        self._mismatch_noted &= ctx.seen
        return ResolveCiResponse(ci_resolved=ci_resolved, ci_unread=ctx.ci_unread)

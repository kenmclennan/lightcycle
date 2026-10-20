from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import flow_for, run_of, skip_unpinned
from lightcycle.domain.pool import ci_outcome, failing_check
from lightcycle.domain.work import State
from lightcycle.ports.github import NotYetRead, ReadFailure


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
    def __init__(self, store, github, flow_service, complete, *, clock, poll_seconds):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._unread = {}

    def _note_unread(self, step, reason, failure, still_unread, ci_unread):
        now = self._clock()
        since, _, logged = self._unread.get(step.id, (now, reason, None))
        still_unread.add(step.id)
        if now - since > self._poll_seconds() and reason != logged:
            logged = reason
            ci_unread.append(CiUnread(step.id, reason, getattr(failure, "stderr", "") or ""))
        self._unread[step.id] = (since, reason, logged)

    def execute(self) -> ResolveCiResponse:
        ci_resolved = []
        ci_unread = []
        still_unread = set()
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
            outcome = ci_outcome(checks)
            if outcome == "pending":
                continue
            if outcome == "success" and sd.ci_success:
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                self._complete.execute(CompleteInput(
                    step=step.id, outcome=sd.ci_success, note="CI succeeded on %s." % sha,
                ))
                ci_resolved.append(step.item)
            elif outcome == "failure" and sd.ci_failure:
                if self._github.head_sha(pr_value) != sha:
                    continue
                self._store.add_artifact(step.id, "ci-judged-sha", sha, internal=True)
                fc = failing_check(checks)
                url = " %s" % fc.url if fc and fc.url else ""
                note = "CI failed on %s: check '%s'%s, PR %s." % (
                    sha, fc.name if fc else "unknown", url, pr_value,
                )
                self._complete.execute(CompleteInput(step=step.id, outcome=sd.ci_failure, note=note))
                ci_resolved.append(step.item)
        for step_id in [k for k in self._unread if k not in still_unread]:
            del self._unread[step_id]
        return ResolveCiResponse(ci_resolved=ci_resolved, ci_unread=ci_unread)

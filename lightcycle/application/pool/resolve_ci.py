from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.pr_lookups import flow_for, run_of
from lightcycle.domain.pool import ci_outcome, failing_check
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure


@dataclass(frozen=True)
class ResolveCiResponse:
    ci_resolved: List[str] = field(default_factory=list)


class ResolveCiUseCase:
    def __init__(self, store, github, flow_service, complete):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._complete = complete

    def execute(self) -> ResolveCiResponse:
        ci_resolved = []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE or step.role != "engine":
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
            if isinstance(sha, ReadFailure) or not sha:
                continue
            checks = self._github.check_runs(pr_value, sha)
            if isinstance(checks, ReadFailure):
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
        return ResolveCiResponse(ci_resolved=ci_resolved)

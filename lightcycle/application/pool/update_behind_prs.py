from dataclasses import dataclass, field
from typing import List

from lightcycle.application.pool.pr_lookups import flow_for, run_of
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure

UPDATE_CAP = 3
RULE_TTL_SECONDS = 300


@dataclass(frozen=True)
class UpdateBehindPrsResponse:
    updated: List[str] = field(default_factory=list)
    update_failed: List[str] = field(default_factory=list)


def _first_line(text):
    lines = (text or "").strip().splitlines()
    return lines[0] if lines else ""


class UpdateBehindPrsUseCase:
    def __init__(self, store, github, flow_service, clock):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._clock = clock
        self._rule_cache = {}
        self._attempted = set()
        self._update_counts = {}
        self._cap_noted = set()

    def _note_failure(self, step_id, what, failure):
        self._store.note_condition(
            step_id, "%s (exit %d): %s" % (what, failure.returncode, _first_line(failure.stderr))
        )

    def _requires_up_to_date(self, base_key):
        now = self._clock()
        cached = self._rule_cache.get(base_key)
        if cached is not None and now < cached[1]:
            return cached[0]
        value = self._github.requires_up_to_date(base_key)
        self._rule_cache[base_key] = (value, now + RULE_TTL_SECONDS)
        return value

    def execute(self, reads=None) -> UpdateBehindPrsResponse:
        reads = reads or PrSyncReads(self._github)
        updated, update_failed = [], []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE or not step.item:
                continue
            flow = flow_for(self._flow_service, step)
            if flow.step_def(step.stage).pr_merge is None:
                continue
            run = run_of(self._store, self._flow_service, step)
            pr = run.pr if run else None
            if pr is None:
                continue
            self._update(step, pr, reads, updated, update_failed)
        return UpdateBehindPrsResponse(updated=updated, update_failed=update_failed)

    def _update(self, step, pr, reads, updated, update_failed):
        sync = reads.read(pr)
        if isinstance(sync, ReadFailure):
            self._note_failure(step.id, "gh read failed while checking whether the PR is behind", sync)
            return
        if not sync.behind:
            return
        if (pr, sync.head_sha) in self._attempted:
            return
        if self._update_counts.get(pr, 0) >= UPDATE_CAP:
            if pr not in self._cap_noted:
                self._cap_noted.add(pr)
                self._store.note_condition(
                    step.id,
                    "update cap reached (%d updates), update the branch by hand" % UPDATE_CAP,
                )
            return
        required = self._requires_up_to_date(sync.base_key)
        if isinstance(required, ReadFailure):
            self._note_failure(
                step.id, "gh read failed while checking the base's up-to-date rule", required
            )
            return
        if not required:
            return
        self._attempted.add((pr, sync.head_sha))
        failure = self._github.update_branch(pr, sync.head_sha)
        if isinstance(failure, ReadFailure):
            self._note_failure(step.id, "update-branch refused", failure)
            update_failed.append(step.item)
            return
        self._update_counts[pr] = self._update_counts.get(pr, 0) + 1
        base = sync.base_key.partition("@")[2]
        self._store.note_condition(
            step.id,
            "Branch updated onto %s through GitHub update-branch (rebase) from %s; "
            "CI is re-running on the new head. Do not merge until it is green."
            % (base, sync.head_sha[:7]),
        )
        updated.append(step.item)

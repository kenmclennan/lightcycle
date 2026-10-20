from dataclasses import dataclass, field
from typing import List

from lightcycle.application.pool.pr_lookups import flow_for, run_of
from lightcycle.application.pool.pr_sync_reads import PrSyncReads
from lightcycle.application.pool.pr_writes import (
    NOT_REQUIRED,
    RULE_FAILED,
    UPDATE_FAILED,
)
from lightcycle.application.work.behind_reason import behind_reason
from lightcycle.domain.work import State
from lightcycle.domain.work.behind_marker import BEHIND_NOT_UPDATED
from lightcycle.ports.github import NotYetRead, ReadFailure

UPDATE_CAP = 3


@dataclass(frozen=True)
class UpdateBehindPrsResponse:
    updated: List[str] = field(default_factory=list)
    update_failed: List[str] = field(default_factory=list)


def _first_line(text):
    lines = (text or "").strip().splitlines()
    return lines[0] if lines else ""


class UpdateBehindPrsUseCase:
    def __init__(self, store, github, flow_service, writes):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._writes = writes
        self._pending = {}
        self._attempted = set()
        self._streaks = {}
        self._cap_noted = set()

    def _note_failure(self, step_id, what, failure):
        if isinstance(failure, NotYetRead):
            return
        self._store.note_condition(
            step_id, "%s (exit %d): %s" % (what, failure.returncode, _first_line(failure.stderr))
        )

    def _set_marker(self, step_id, text):
        if behind_reason(self._store, step_id) != (text or None):
            self._store.replace_artifact(step_id, BEHIND_NOT_UPDATED, text, internal=True)

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
        streak = self._streaks.get(pr)
        if streak is not None and streak[0] != step.id:
            del self._streaks[pr]
        count = self._streaks[pr][1] if pr in self._streaks else 0
        sync = reads.read(pr)
        if pr in self._pending:
            outcome = self._writes.take_outcome(pr)
            if outcome is None:
                return
            head_sha, base_key = self._pending.pop(pr)
            self._apply(step, pr, head_sha, base_key, count, outcome, updated, update_failed)
            return
        if isinstance(sync, ReadFailure):
            self._note_failure(step.id, "gh read failed while checking whether the PR is behind", sync)
            return
        if not sync.behind:
            self._set_marker(step.id, "")
            return
        if (pr, sync.head_sha) in self._attempted:
            return
        if count >= UPDATE_CAP:
            if step.id not in self._cap_noted:
                self._cap_noted.add(step.id)
                self._store.note_condition(
                    step.id,
                    "update cap reached (%d updates), update the branch by hand" % UPDATE_CAP,
                )
            self._set_marker(step.id, "update cap reached (%d updates)" % UPDATE_CAP)
            return
        self._writes.request_update(pr, sync.head_sha, sync.base_key)
        self._pending[pr] = (sync.head_sha, sync.base_key)
        outcome = self._writes.take_outcome(pr)
        if outcome is None:
            return
        del self._pending[pr]
        self._apply(step, pr, sync.head_sha, sync.base_key, count, outcome, updated, update_failed)

    def _apply(self, step, pr, head_sha, base_key, count, outcome, updated, update_failed):
        if outcome.kind == RULE_FAILED:
            self._note_failure(
                step.id, "gh read failed while checking the base's up-to-date rule",
                outcome.failure,
            )
            return
        if outcome.kind == NOT_REQUIRED:
            self._set_marker(step.id, "")
            return
        self._attempted.add((pr, head_sha))
        if outcome.kind == UPDATE_FAILED:
            self._note_failure(step.id, "update-branch refused", outcome.failure)
            self._set_marker(step.id, "update-branch refused")
            update_failed.append(step.item)
            return
        self._streaks[pr] = (step.id, count + 1)
        self._set_marker(step.id, "")
        base = base_key.partition("@")[2]
        self._store.note_condition(
            step.id,
            "Branch updated onto %s through GitHub update-branch (rebase) from %s; "
            "CI is re-running on the new head. Do not merge until it is green."
            % (base, head_sha[:7]),
        )
        updated.append(step.item)

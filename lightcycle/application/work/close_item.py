from dataclasses import dataclass
from typing import FrozenSet, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.resolve_backlog import retire_resolved
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State

TEARDOWN_REFUSED_ARTIFACT = "teardown-refused"
RELEASE_PENDING_LABEL = "release-pending"


class TeardownRefused(UseCaseError):
    def __init__(self, item, findings):
        self.item = item
        self.findings = list(findings)
        super().__init__(
            "cannot close %s: %s. Commit, push or discard that work, then close the item again."
            % (item, "; ".join(self.findings))
        )


@dataclass(frozen=True)
class CloseItemInput:
    item: str
    reason: str
    disposition: str
    note: Optional[str] = None
    merged_prs: FrozenSet[str] = frozenset()


class CloseItemUseCase:
    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees

    def teardown_findings(self, input: CloseItemInput):
        if self._worktrees is None:
            return []
        return self._worktrees.teardown_refusals(input.item, input.merged_prs)

    def record_refusal(self, item, findings) -> TeardownRefused:
        refusal = TeardownRefused(item, findings)
        with self._store.transaction():
            self._store.replace_artifact(
                item, TEARDOWN_REFUSED_ARTIFACT, str(refusal), internal=True
            )
            self._park_open_step(item, "; ".join(findings))
        return refusal

    def _refuse_if_unsafe(self, input: CloseItemInput) -> None:
        findings = self.teardown_findings(input)
        if findings:
            raise self.record_refusal(input.item, findings)

    def _park_open_step(self, item, finding_text: str) -> None:
        step = next((s for s in self._store.children(item) if s.state != State.DONE), None)
        if step is None:
            return
        decision = "commit, push or discard the work named, then close %s again" % item
        ParkStepUseCase(self._store).execute_once(
            ParkInput(step=step.id, observation=self._observation(finding_text), decision=decision)
        )

    @staticmethod
    def _observation(finding_text: str) -> str:
        return "item close refused: %s" % finding_text

    def close_in_transaction(self, input: CloseItemInput) -> None:
        for kt in self._store.children(input.item):
            if kt.state != State.DONE:
                self._store.complete_node(kt.id, input.reason)
        self._store.complete_node(input.item, input.reason, input.disposition, input.note)
        for run in self._store.open_runs_of(input.item):
            self._store.close_run(run.id, RunState.ABANDONED)
        current = self._store.current_pass(input.item)
        if current is not None:
            self._store.close_pass(current.id)
        retire_resolved(self._store, input.item)
        self._store.remove_artifact(input.item, TEARDOWN_REFUSED_ARTIFACT)
        if self._worktrees is not None:
            self._store.label_add(input.item, RELEASE_PENDING_LABEL)

    def release(self, item) -> None:
        if self._worktrees is None:
            return
        self._worktrees.remove(item)
        self._store.label_remove(item, RELEASE_PENDING_LABEL)

    def execute(self, input: CloseItemInput) -> None:
        self._refuse_if_unsafe(input)
        with self._store.transaction():
            self.close_in_transaction(input)
        self.release(input.item)

from dataclasses import dataclass
from typing import FrozenSet, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.park_step import ParkInput, ParkStepUseCase
from lightcycle.application.work.resolve_backlog import retire_resolved
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State

TEARDOWN_REFUSED_ARTIFACT = "teardown-refused"


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

    def _refuse_if_unsafe(self, input: CloseItemInput) -> None:
        if self._worktrees is None:
            return
        findings = self._worktrees.teardown_refusals(input.item, input.merged_prs)
        if not findings:
            return
        refusal = TeardownRefused(input.item, findings)
        with self._store.transaction():
            self._store.replace_artifact(
                input.item, TEARDOWN_REFUSED_ARTIFACT, str(refusal), internal=True
            )
            self._park_open_step(input.item, "; ".join(findings))
        raise refusal

    def _park_open_step(self, item, finding_text: str) -> None:
        step = next((s for s in self._store.children(item) if s.state != State.DONE), None)
        if step is None:
            return
        decision = "commit, push or discard the work named, then close %s again" % item
        if step.park.needs == decision and step.park.reason == self._observation(finding_text):
            return
        ParkStepUseCase(self._store).execute(
            ParkInput(step=step.id, observation=self._observation(finding_text), decision=decision)
        )

    @staticmethod
    def _observation(finding_text: str) -> str:
        return "item close refused: %s" % finding_text

    def execute(self, input: CloseItemInput) -> None:
        self._refuse_if_unsafe(input)
        with self._store.transaction():
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
        if self._worktrees is not None:
            self._worktrees.remove(input.item)

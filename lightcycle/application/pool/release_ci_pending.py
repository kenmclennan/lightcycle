from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.unblock_step import UnblockInput, UnblockStepUseCase
from lightcycle.application.pool.pr_lookups import run_of
from lightcycle.domain.work import State
from lightcycle.ports.github import ReadFailure

CI_PENDING_LABEL = "ci-pending"
CI_RELEASED_PREFIX = "ci-released:"


@dataclass(frozen=True)
class ReleaseCiPendingResponse:
    released: List[str] = field(default_factory=list)


class ReleaseCiPendingUseCase:
    def __init__(self, store, github, flow_service, spin_port, config):
        self._store = store
        self._github = github
        self._flow_service = flow_service
        self._spin_port = spin_port
        self._config = config

    def execute(self) -> ReleaseCiPendingResponse:
        released = []
        for step in self._store.all_nodes():
            if step.type != "step" or step.state == State.DONE:
                continue
            if step.role != "human":
                continue
            labels = self._store.labels_of(step.id)
            if CI_PENDING_LABEL not in labels:
                continue
            run = run_of(self._store, self._flow_service, step)
            pr_value = run.pr if run else None
            if not pr_value:
                continue
            sha = self._github.head_sha(pr_value)
            if isinstance(sha, ReadFailure) or not sha:
                continue
            pending = self._github.ci_pending(pr_value, sha)
            if isinstance(pending, ReadFailure) or pending:
                continue
            released_so_far = sum(1 for l in labels if l.startswith(CI_RELEASED_PREFIX))
            cap = self._config.ci_release_cap()
            if released_so_far >= cap:
                self._store.note_condition(
                    step.id,
                    "CI concluded but the automatic release cap (%d) was already reached; "
                    "a human must resume this step." % cap,
                )
                continue
            with self._store.transaction():
                UnblockStepUseCase(
                    self._store, self._flow_service, spin_port=self._spin_port
                ).execute(UnblockInput(step=step.id))
                self._store.label_remove(step.id, CI_PENDING_LABEL)
                self._store.label_add(
                    step.id, "%s%d" % (CI_RELEASED_PREFIX, released_so_far + 1)
                )
            released.append(step.parent)
        return ReleaseCiPendingResponse(released=released)

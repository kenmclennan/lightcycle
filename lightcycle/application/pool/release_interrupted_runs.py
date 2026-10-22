from dataclasses import dataclass, field
from typing import List, Tuple

from lightcycle.application.pool.pr_lookups import active_step_any
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State
from lightcycle.ports.git import GitReadError


@dataclass(frozen=True)
class ReleaseInterruptedRunsResponse:
    released: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)


class ReleaseInterruptedRunsUseCase:
    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees
        self._pending = None

    def _candidates(self):
        found = []
        for item in self._store.all_items():
            step = active_step_any(self._store, item.id)
            if step is None or step.state not in (State.QUEUED, State.RUNNING):
                continue
            runs = self._store.runs_of(item.id)
            open_runs = [r for r in runs if r.state == RunState.OPEN]
            open_branches = {r.branch for r in open_runs if r.branch}
            open_paths = {self._worktrees.path_for_run(r) for r in open_runs}
            for run in runs:
                if run.state == RunState.OPEN or not run.branch:
                    continue
                if run.branch in open_branches:
                    continue
                if self._worktrees.path_for_run(run) in open_paths:
                    continue
                found.append(run)
        return found

    def execute(self) -> ReleaseInterruptedRunsResponse:
        if self._pending is None:
            self._pending = self._candidates()
        released = []
        failed = []
        remaining = []
        for run in self._pending:
            try:
                if self._worktrees.release_interrupted(run):
                    released.append(run.id)
            except GitReadError as e:
                failed.append((run.id, str(e)))
                remaining.append(run)
        self._pending = remaining
        return ReleaseInterruptedRunsResponse(released=released, failed=failed)

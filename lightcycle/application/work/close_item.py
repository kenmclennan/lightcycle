from dataclasses import dataclass

from lightcycle.application.work.resolve_backlog import retire_resolved
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State


@dataclass(frozen=True)
class CloseItemInput:
    item: str
    reason: str


class CloseItemUseCase:
    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees

    def execute(self, input: CloseItemInput) -> None:
        for kt in self._store.children(input.item):
            if kt.state != State.DONE:
                self._store.close(kt.id, input.reason)
        self._store.close(input.item, input.reason)
        for run in self._store.open_runs_of(input.item):
            self._store.close_run(run.id, RunState.ABANDONED)
        current = self._store.current_pass(input.item)
        if current is not None:
            self._store.close_pass(current.id)
        self._worktrees.remove(input.item)
        retire_resolved(self._store, input.item)

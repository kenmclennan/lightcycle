from dataclasses import dataclass

from lightcycle.application.work.resolve_backlog import retire_resolved
from lightcycle.domain.runs import RunState
from lightcycle.domain.work import State


@dataclass(frozen=True)
class CloseItemInput:
    item: str
    reason: str
    disposition: str


class CloseItemUseCase:
    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees

    def execute(self, input: CloseItemInput) -> None:
        with self._store.transaction():
            for kt in self._store.children(input.item):
                if kt.state != State.DONE:
                    self._store.complete_node(kt.id, input.reason)
            self._store.complete_node(input.item, input.reason, input.disposition)
            for run in self._store.open_runs_of(input.item):
                self._store.close_run(run.id, RunState.ABANDONED)
            current = self._store.current_pass(input.item)
            if current is not None:
                self._store.close_pass(current.id)
            retire_resolved(self._store, input.item)
        if self._worktrees is not None:
            self._worktrees.remove(input.item)

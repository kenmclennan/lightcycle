from dataclasses import dataclass

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
        self._worktrees.remove(input.item)

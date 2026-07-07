from dataclasses import dataclass


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
            if kt.status != "done":
                self._store.close(kt.id, input.reason)
        self._store.close(input.item, input.reason)
        self._worktrees.remove(input.item)

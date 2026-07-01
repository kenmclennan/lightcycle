"""CloseStory: close a story and its open tasks, then tear down its worktree."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CloseStoryInput:
    story: str
    reason: str


class CloseStoryUseCase:

    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees

    def execute(self, input: CloseStoryInput) -> None:
        for kt in self._store.children(input.story):
            if kt.status != "done":
                self._store.close(kt.id, input.reason)
        self._store.close(input.story, input.reason)
        self._worktrees.remove(input.story)

"""CloseStory: close a story and its open tasks, then tear down its worktree."""


class CloseStory:

    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees

    def execute(self, story, reason):
        for kt in self._store.children(story):
            if kt.status != "done":
                self._store.close(kt.id, reason)
        self._store.close(story, reason)
        self._worktrees.remove(story)

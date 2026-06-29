"""CloseStory: close a story and its open tasks, then tear down its worktree."""
from the_grid.core.tasks import task_from_bead


class CloseStory:

    def __init__(self, store, worktrees):
        self._store = store
        self._worktrees = worktrees

    def execute(self, story, reason):
        for k in self._store.children(story):
            kt = task_from_bead(k)
            if kt["status"] != "done":
                self._store.close(kt["id"], reason)
        self._store.close(story, reason)
        self._worktrees.remove(story)

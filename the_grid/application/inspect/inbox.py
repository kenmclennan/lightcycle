"""Inbox: what needs a human now - human-owned steps and agent blocks."""
from the_grid.domain.work import TaskQueue


class Inbox:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, n=None):
        queue = TaskQueue(self._store.all_tasks())
        return queue.for_human(self._flow.load_flow(), {"action", "blocked"}, n)

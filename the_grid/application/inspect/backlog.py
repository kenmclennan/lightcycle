"""Backlog: todo items to develop later (human tasks with no step)."""
from the_grid.domain.work import TaskQueue


class Backlog:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, n=None):
        queue = TaskQueue(self._store.all_tasks())
        return queue.for_human(self._flow.load_flow(), {"todo"}, n)

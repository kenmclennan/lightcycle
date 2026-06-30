"""List the next N ready or blocked agent tasks."""
from the_grid.domain.work import TaskQueue


class Queue:

    def __init__(self, store):
        self._store = store

    def execute(self, n=10):
        queue = TaskQueue(self._store.all_tasks())
        return (queue.by_status("ready") + queue.by_status("blocked"))[:n]

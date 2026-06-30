"""Bucket all tasks into inbox / active / queue / blocked."""
from the_grid.domain.work import TaskQueue


class Status:

    def __init__(self, store):
        self._store = store

    def execute(self):
        return TaskQueue(self._store.all_tasks()).bucket()

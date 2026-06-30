"""Bucket all tasks into inbox / active / queue / blocked."""
from the_grid.domain import tasks as ctasks


class Status:

    def __init__(self, store):
        self._store = store

    def execute(self):
        return ctasks.bucket(self._store.all_tasks())

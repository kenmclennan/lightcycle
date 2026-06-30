"""List tasks a worker is running right now (in-progress)."""
from the_grid.domain import tasks as ctasks


class ActiveTasks:

    def __init__(self, store):
        self._store = store

    def execute(self):
        return ctasks.filter_by_status(self._store.all_tasks(), "in-progress")

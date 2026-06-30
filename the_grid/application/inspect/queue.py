"""List the next N ready or blocked agent tasks."""
from the_grid.domain import tasks as ctasks


class Queue:

    def __init__(self, store):
        self._store = store

    def execute(self, n=10):
        tasks = self._store.all_tasks()
        ready = ctasks.filter_by_status(tasks, "ready")
        blocked = ctasks.filter_by_status(tasks, "blocked")
        return (ready + blocked)[:n]

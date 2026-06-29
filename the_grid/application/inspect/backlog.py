"""Backlog: todo items to develop later (human tasks with no step)."""
from the_grid.core import tasks as ctasks


class Backlog:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, n=None):
        owner, routes = self._flow.load_flow()
        tasks = ctasks.filter_by_status(self._store.all_tasks(), "needs-human")
        return ctasks.partition_mine(tasks, owner, routes, {"todo"}, n)

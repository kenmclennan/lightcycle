"""Inbox: what needs a human now - human-owned steps and agent blocks."""
from the_grid.domain import tasks as ctasks


class Inbox:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, n=None):
        owner, routes = self._flow.load_flow()
        tasks = ctasks.filter_by_status(self._store.all_tasks(), "needs-human")
        return ctasks.partition_mine(tasks, owner, routes, {"action", "blocked"}, n)

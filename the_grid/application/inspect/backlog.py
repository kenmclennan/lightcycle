"""Backlog: todo items to develop later (human tasks with no step)."""
from the_grid.domain import tasks as ctasks


class Backlog:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, n=None):
        flow = self._flow.load_flow()
        owner, routes = flow.owner_map(), flow.routes_map()
        tasks = ctasks.filter_by_status(self._store.all_tasks(), "needs-human")
        return ctasks.partition_mine(tasks, owner, routes, {"todo"}, n)

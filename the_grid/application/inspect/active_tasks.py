"""List tasks a worker is running right now (in-progress)."""
from the_grid.domain.work import TaskQueue


class ActiveTasks:

    def __init__(self, store):
        self._store = store

    def execute(self):
        return TaskQueue(self._store.all_tasks()).by_status("in-progress")

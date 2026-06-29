"""Mine (deprecated): all human tasks combined, ordered blocked > action > todo."""
from the_grid.core import tasks as ctasks

_MINE_ORDER = {"blocked": 0, "action": 1, "todo": 2}


class Mine:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self):
        owner, routes = self._flow.load_flow()
        tasks = ctasks.filter_by_status(self._store.all_tasks(), "needs-human")
        rows = [(ctasks.classify_mine(t, owner, routes), t) for t in tasks]
        rows.sort(key=lambda r: (_MINE_ORDER.get(r[0][0], 9), r[1]["id"]))
        return rows

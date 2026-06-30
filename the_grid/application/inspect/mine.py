"""Mine (deprecated): all human tasks combined, ordered blocked > action > todo."""
from the_grid.domain.work import TaskQueue

_MINE_ORDER = {"blocked": 0, "action": 1, "todo": 2}


class Mine:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self):
        queue = TaskQueue(self._store.all_tasks())
        rows = queue.for_human(self._flow.load_flow(), {"todo", "action", "blocked"})
        rows.sort(key=lambda r: (_MINE_ORDER.get(r[0][0], 9), r[1].id))
        return rows

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work.open_successors import open_successors
from lightcycle.domain.work.state import State


class ReopenGuard:
    def __init__(self, store):
        self._store = store

    def ensure_reopenable(self, step_id):
        node = self._store.get_node(step_id)
        if getattr(node, "type", None) != "step" or node.state != State.DONE:
            return
        children = self._store.children(node.item)
        open_ids = open_successors(step_id, children)
        if not open_ids:
            return
        by_id = {c.id: c for c in children}
        named = ", ".join(
            "%s (%s)" % (i, by_id[i].stage or by_id[i].role) for i in open_ids)
        raise UseCaseError(
            "cannot re-open closed step %s: its successor is still open: %s; "
            "remove it (lc rm) or close it (lc done) first" % (step_id, named)
        )

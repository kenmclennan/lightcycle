"""AdvanceTask: create the next task in the flow for an outcome (no closing)."""
from the_grid.core import flow as cflow


class AdvanceTask:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, tid, outcome):
        t = self._store.get_task(tid)
        nxt = self._flow.flow_next(t["step"], outcome)
        if nxt is None:
            return None
        next_step, next_role = nxt
        return self._store.create_task(**cflow.advance_create_kwargs(t, next_step, next_role))

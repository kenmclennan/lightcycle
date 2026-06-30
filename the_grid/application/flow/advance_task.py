"""AdvanceTask: create the next task in the flow for an outcome (no closing)."""


class AdvanceTask:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, tid, outcome):
        t = self._store.get_task(tid)
        transition = self._flow.flow_next(t.step, outcome)
        if transition is None:
            return None
        return self._store.create_task(**transition.next_task_spec(t))

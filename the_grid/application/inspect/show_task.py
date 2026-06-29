"""Show one task or story as a view dict (artifacts + resume-state)."""


class ShowTask:

    def __init__(self, store):
        self._store = store

    def execute(self, tid):
        return self._store.task_view(tid)

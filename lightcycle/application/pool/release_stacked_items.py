from lightcycle.application.work.stack_runs import StackRuns


class ReleaseStackedItemsUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._stack_runs = StackRuns(store, flow)

    def execute(self):
        released = []
        for item in self._store.all_items():
            parent = item.stacks_on
            if not parent:
                continue
            gated = [s for s in self._store.children(item.id) if parent in s.blocked_by]
            if not gated:
                continue
            run = self._stack_runs.run_of(parent)
            if run is None or not run.pr:
                continue
            for step in gated:
                self._store.dep_remove(step.id, parent)
                released.append(step.id)
        return released

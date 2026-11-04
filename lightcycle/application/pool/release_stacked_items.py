from lightcycle.application.work.stack_runs import StackRuns
from lightcycle.domain.work.state import State


class ReleaseStackedItemsUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._stack_runs = StackRuns(store, flow)

    def execute(self):
        released = []
        for item in self._store.all_items():
            released.extend(self._release_slices(item))
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

    def _release_slices(self, item):
        gated = [
            s for s in self._store.children(item.id)
            if s.slice > 0 and s.state != State.DONE and item.id in s.blocked_by
        ]
        if not gated:
            return []
        pass_record = self._store.current_pass(item.id)
        if pass_record is None:
            return []
        runs = self._store.runs_of(item.id, pass_record.id)
        released = []
        for step in gated:
            run = self._run_of_step(runs, step)
            if run is None or run.base_slice is None:
                continue
            base = self._latest(runs, run.phase, run.base_slice)
            if base is None or not base.pr:
                continue
            self._store.dep_remove(step.id, item.id)
            released.append(step.id)
        return released

    def _latest(self, runs, phase, slice):
        matching = [r for r in runs if r.phase == phase and r.slice == slice]
        return matching[-1] if matching else None

    def _run_of_step(self, runs, step):
        matching = [r for r in runs if r.slice == step.slice and r.phase is not None]
        return matching[-1] if matching else None

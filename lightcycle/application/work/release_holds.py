from lightcycle.application.work.close_item import RELEASE_PENDING_LABEL


class ReleaseHolds:
    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def held_ids(self, steps):
        marked = {item.id for item in self._store.items_with_label(RELEASE_PENDING_LABEL)}
        if not marked:
            return set()
        return {s.id for s in steps if s.item in marked and self._touches_worktree(s)}

    def _touches_worktree(self, step):
        if step.role != "engine":
            return True
        if self._flow.unpinned_workflow(step) is not None:
            return False
        sd = self._flow.flow_for(step).step_def(step.stage)
        return bool(sd.script) and sd.workspace is not None

    def release_pending_items(self):
        return {item.id for item in self._store.items_with_label(RELEASE_PENDING_LABEL)}

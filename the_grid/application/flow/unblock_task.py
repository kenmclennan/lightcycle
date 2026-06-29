"""UnblockTask: flip a blocked task back to its agent role so it re-claims."""
from the_grid.application.errors import UseCaseError


class UnblockTask:

    def __init__(self, store, flow):
        self._store = store
        self._flow = flow

    def execute(self, tid):
        t = self._store.get_task(tid)
        owner, _ = self._flow.load_flow()
        role = owner.get(t["step"])
        if not role or role == "human":
            raise UseCaseError(
                "nothing to unblock: step '%s' has no agent owner" % (t["step"] or "(none)"))
        cur = t["role"]
        if cur and cur != role:
            self._store.label_remove(tid, "for:%s" % cur)
        self._store.label_add(tid, "for:%s" % role)
        self._store.update_status(tid, "open")
        self._store.assign(tid, "")
        return role

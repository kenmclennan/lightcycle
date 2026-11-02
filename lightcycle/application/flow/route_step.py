from lightcycle.application.flow.reopen_guard import ReopenGuard
from lightcycle.domain.work.derive import role_state


class RouteStepService:
    def __init__(self, store):
        self._store = store

    def route(self, step, role):
        ReopenGuard(self._store).ensure_reopenable(step)
        cur = getattr(self._store.get_node(step), "role", None)
        if cur and cur != role:
            self._store.label_remove(step, "for:%s" % cur)
        self._store.label_add(step, "for:%s" % role)
        self._store.update_state(step, role_state(role))
        self._store.assign(step, "")

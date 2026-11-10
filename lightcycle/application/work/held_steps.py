from lightcycle.application.errors import UseCaseError
from lightcycle.domain.pool import WorkerPool
from lightcycle.domain.work import State
from lightcycle.ports.workers import RegistryUnreadable


class HeldSteps:
    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def holder(self, step):
        if step.state != State.RUNNING:
            return None
        try:
            state = self._workers.workers_state()
        except RegistryUnreadable as e:
            raise UseCaseError(
                "could not tell whether a worker is running %s - %s" % (step.id, e)
            )
        return WorkerPool(state).holding(self._workers.pid_alive, step.id, step.claimed_by)

    def of_item(self, item):
        held = []
        for child in self._store.children(item):
            if child.type != "step" or child.state == State.DONE:
                continue
            worker = self.holder(child)
            if worker is not None:
                held.append((child, worker))
        return held

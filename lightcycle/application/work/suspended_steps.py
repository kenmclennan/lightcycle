from lightcycle.domain.pool.worker_pool import WorkerPool
from lightcycle.ports.workers import RegistryUnreadable


def suspended_step_ids(workers):
    try:
        pool = WorkerPool(workers.workers_state())
    except RegistryUnreadable:
        return frozenset()
    return frozenset(w.step for w in pool.alive(workers.pid_alive) if w.step and w.suspended)

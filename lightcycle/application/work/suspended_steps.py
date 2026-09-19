from lightcycle.ports.workers import RegistryUnreadable


def suspended_step_ids(workers):
    try:
        return frozenset(w.step for w in workers.workers_state() if w.step and w.suspended)
    except RegistryUnreadable:
        return frozenset()

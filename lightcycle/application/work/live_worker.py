from lightcycle.domain.pool import WorkerPool


def live_claimed_step(store, workers, step_ids):
    if not step_ids:
        return None
    pool = WorkerPool(workers.workers_state())
    covered = pool.covered_steps(workers.pid_alive)
    live_spawnids = pool.live_spawnids(workers.pid_alive)
    for t in store.claimed_steps():
        if t.id in step_ids and (t.id in covered or t.claimed_by in live_spawnids):
            return t.id
    return None

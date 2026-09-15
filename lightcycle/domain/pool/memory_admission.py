def admission_cap(headroom, alive_count, memory_reserve_fraction):
    if headroom is None or headroom.pool_share is None:
        return None
    per_worker = headroom.pool_share / alive_count if alive_count else 0.0
    projected = headroom.pool_share + per_worker
    if projected > (1.0 - memory_reserve_fraction):
        return 1 if alive_count == 0 else 0
    return None


def worker_to_suspend(alive_workers, pressure, suspend_pressure):
    if pressure is None or pressure < suspend_pressure:
        return None
    candidates = [w for w in alive_workers if not w.suspended]
    return max(candidates, key=lambda w: w.started, default=None)


def worker_to_resume(alive_workers, pressure, resume_pressure):
    if pressure is not None and pressure >= resume_pressure:
        return None
    candidates = [w for w in alive_workers if w.suspended]
    return max(candidates, key=lambda w: w.suspended_at or 0, default=None)

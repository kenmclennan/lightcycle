from lightcycle.domain.pool.worker import Worker


class WorkerPool:
    def __init__(self, workers):
        self._workers = list(workers)

    @classmethod
    def from_state(cls, state) -> "WorkerPool":
        return cls(Worker.from_state(d) for d in state)

    def alive(self, probe):
        return [w for w in self._workers if w.is_alive(probe)]

    def free_slots(self, max_agents, probe):
        return max_agents - len(self.alive(probe))

    def live_spawnids(self, probe):
        return {w.spawnid for w in self._workers if w.spawnid and w.is_alive(probe)}

    def inflight(self, probe, now, max_boot):
        counts = {}
        for w in self.alive(probe):
            if w.is_booting(now, max_boot):
                counts[w.role] = counts.get(w.role, 0) + 1
        return counts

    def covered_steps(self, probe):
        return {w.step for w in self.alive(probe) if w.step}

    def any_booting(self, probe, now, max_boot):
        return any(w.is_booting(now, max_boot) for w in self.alive(probe))

    def orphans(self, probe, now, max_boot, claimed_ids):
        return [
            w
            for w in self.alive(probe)
            if w.spawnid
            and not w.is_booting(now, max_boot)
            and (w.step is None or w.step not in claimed_ids)
        ]

    def dead_unchecked(self, probe):
        return [w for w in self._workers if w.spawnid and not w.checked and not w.is_alive(probe)]

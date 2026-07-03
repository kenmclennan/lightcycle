from the_grid.domain.pool.worker import Worker


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

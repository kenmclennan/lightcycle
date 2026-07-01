"""PoolPlan: the spawn decision for one tick (a value object)."""


class PoolPlan:

    def __init__(self, inflight, slots):
        self._inflight = dict(inflight)
        self._slots = slots

    def roles_to_spawn(self, roles):
        """Which roles to spawn this tick: one entry per new worker, in queue order,
        capped at free slots. A booting worker of a role already covers one ready task
        of that role (inflight), so it is not re-spawned."""
        inflight = dict(self._inflight)
        out = []
        for role in roles:
            if len(out) >= self._slots:
                break
            if inflight.get(role, 0) > 0:
                inflight[role] -= 1
                continue
            out.append(role)
        return out

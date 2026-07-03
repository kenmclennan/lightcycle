class PoolPlan:
    def __init__(self, inflight, slots):
        self._inflight = dict(inflight)
        self._slots = slots

    def roles_to_spawn(self, roles):
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

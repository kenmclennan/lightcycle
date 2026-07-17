from lightcycle.domain.work.lane import Lane
from lightcycle.domain.work.state import State, lane_for


class NodeQueue:
    def __init__(self, steps):
        self._steps = list(steps)

    def by_state(self, state):
        return [t for t in self._steps if t.state == state]

    def by_lane(self):
        lanes = {lane.value: [] for lane in Lane}
        for t in self._steps:
            lanes[lane_for(t.state, t.role).value].append(t)
        return lanes

    def for_human(self, resolve_flow, kinds, n=None):
        rows = [
            (t.classify_for_human(resolve_flow(t)), t)
            for t in self._steps
            if t.state == State.READY and t.role == "human"
        ]
        rows = [(c, t) for c, t in rows if c[0] in kinds]
        rows.sort(key=lambda r: r[1].id)
        return rows[:n] if n is not None else rows

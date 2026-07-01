"""TaskQueue: a collection of tasks with the status-based groupings (a value object)."""
from the_grid.domain.work.lane import Lane
from the_grid.domain.work.status import Status


class TaskQueue:

    def __init__(self, tasks):
        self._tasks = list(tasks)

    def by_status(self, status):
        return [t for t in self._tasks if t.status == status]

    def by_lane(self, ready_ids):
        """Group tasks into their board lanes. A task whose status puts it in the
        queue but which is not in `ready_ids` has an open blocker, so it lands in
        the blocked lane instead (bd's ready-set is the authority on blocked-ness -
        a task's stored status cannot express it)."""
        lanes = {lane.value: [] for lane in Lane}
        for t in self._tasks:
            lane = Status(t.status).lane
            if lane is Lane.QUEUE and t.id not in ready_ids:
                lane = Lane.BLOCKED
            lanes[lane.value].append(t)
        return lanes

    def for_human(self, flow, kinds, n=None):
        """The needs-human tasks whose classification kind is in `kinds`, each as
        (classification, task), sorted by id and limited to n."""
        rows = [(t.classify_for_human(flow), t) for t in self.by_status("needs-human")]
        rows = [(c, t) for c, t in rows if c[0] in kinds]
        rows.sort(key=lambda r: r[1].id)
        return rows[:n] if n is not None else rows

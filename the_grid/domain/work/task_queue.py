"""TaskQueue: a collection of tasks with the status-based groupings (a value object)."""


class TaskQueue:

    def __init__(self, tasks):
        self._tasks = list(tasks)

    def by_status(self, status):
        return [t for t in self._tasks if t.status == status]

    def bucket(self):
        buckets = {"mine": [], "active": [], "queue": [], "blocked": [], "done": []}
        for t in self._tasks:
            if t.status == "done":
                buckets["done"].append(t)
            elif t.status == "in-progress":
                buckets["active"].append(t)
            elif t.status == "needs-human":
                buckets["mine"].append(t)
            elif t.status == "ready":
                buckets["queue"].append(t)
            else:
                buckets["blocked"].append(t)
        return buckets

    def for_human(self, flow, kinds, n=None):
        """The needs-human tasks whose classification kind is in `kinds`, each as
        (classification, task), sorted by id and limited to n."""
        rows = [(t.classify_for_human(flow), t) for t in self.by_status("needs-human")]
        rows = [(c, t) for c, t in rows if c[0] in kinds]
        rows.sort(key=lambda r: r[1].id)
        return rows[:n] if n is not None else rows

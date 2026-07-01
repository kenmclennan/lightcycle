"""ReadyQueue: the roles waiting for a worker (a value object over ready tasks)."""


class ReadyQueue:

    def __init__(self, tasks):
        self._tasks = list(tasks)

    def roles(self):
        """One role per ready, non-human task - repeats kept. This is the pool's work
        queue: N copies of a role means N tasks waiting."""
        return [t.role for t in self._tasks if t.role and t.role != "human"]

    def distinct_roles(self):
        out = []
        for role in self.roles():
            if role not in out:
                out.append(role)
        return out

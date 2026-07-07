class ReadyQueue:
    def __init__(self, tasks):
        self._tasks = list(tasks)

    def roles(self):
        return [t.role for t in self._tasks if t.role and t.role != "human"]

    def distinct_roles(self):
        out = []
        for role in self.roles():
            if role not in out:
                out.append(role)
        return out

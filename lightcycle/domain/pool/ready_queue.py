class ReadyQueue:
    def __init__(self, steps):
        self._steps = list(steps)

    def roles(self):
        return [t.role for t in self._steps if t.role and t.role != "human"]

    def distinct_roles(self):
        out = []
        for role in self.roles():
            if role not in out:
                out.append(role)
        return out

"""AddTask: create a standalone human task (no spec, no flow)."""


class AddTask:

    def __init__(self, store):
        self._store = store

    def execute(self, title, goal=None, project=None):
        labels = ["for:human"]
        if goal:
            labels.append("goal:%s" % goal)
        if project:
            labels.append("project:%s" % project)
        return self._store.create_task(title, labels=labels)

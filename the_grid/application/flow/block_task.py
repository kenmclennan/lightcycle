"""BlockTask: escalate a task to a human with resume-state."""


class BlockTask:

    def __init__(self, store):
        self._store = store

    def execute(self, tid, needs, branch=None, pr=None, reason=None, tried=None):
        resume = {}
        for k, v in (("branch", branch), ("pr", pr), ("reason", reason),
                     ("tried", tried), ("needs", needs)):
            if v:
                resume[k] = v
        self._store.update_metadata(tid, resume)
        self._store.note(tid, "BLOCKED: %s" % needs)
        role = self._store.get_task(tid).role
        if role and role != "human":
            self._store.label_remove(tid, "for:%s" % role)
        self._store.label_add(tid, "for:human")
        self._store.update_status(tid, "open")
        self._store.assign(tid, "")

"""ListWorkers: the running workers with liveness (role, task, pid, alive/dead)."""


class ListWorkers:

    def __init__(self, workers):
        self._workers = workers

    def execute(self):
        return [dict(w, alive=self._workers.pid_alive(w.get("pid", -1)))
                for w in self._workers.workers_state()]

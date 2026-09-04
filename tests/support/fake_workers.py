class FakeWorkers:
    def __init__(self, workers=None, alive_pids=()):
        self._workers = workers or []
        self._alive = set(alive_pids)
        self.killed = []

    def workers_state(self):
        return list(self._workers)

    def write_workers(self, workers):
        self._workers = list(workers)

    def pid_alive(self, pid, started=None):
        return pid in self._alive

    def reap(self):
        pass

    def kill(self, pid):
        self.killed.append(pid)
        self._alive.discard(pid)

    def prune_workers(self, keep_dead=None):
        return 0

    def set_step(self, spawnid, step):
        for w in self._workers:
            if w.get("spawnid") == spawnid:
                w["step"] = step

    def step_for(self, spawnid):
        for w in self._workers:
            if w.get("spawnid") == spawnid:
                return w.get("step")
        return None

    def mark_checked(self, spawnid):
        pass

    def log_mtime(self, path):
        return None

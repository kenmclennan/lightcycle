"""ResolveLog: resolve a log target (run | task-id | role) to a log file path."""
import os


class ResolveLog:

    def __init__(self, workers, config):
        self._workers = workers
        self._config = config

    def execute(self, target):
        if target == "run":
            return os.path.join(self._config.grid_root(), "logs", "run.log")
        for w in reversed(self._workers.workers_state()):
            if w.get("bead") == target or w.get("role") == target:
                return w["log"]
        return None

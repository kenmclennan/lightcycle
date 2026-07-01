"""ResolveLog: resolve a log target (run | task-id | role) to a log file path."""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResolveLogInput:
    target: str


@dataclass(frozen=True)
class ResolveLogResponse:
    path: Optional[str]


class ResolveLogUseCase:

    def __init__(self, workers, config):
        self._workers = workers
        self._config = config

    def execute(self, input: ResolveLogInput) -> ResolveLogResponse:
        if input.target == "run":
            return ResolveLogResponse(path=os.path.join(self._config.grid_root(), "logs", "run.log"))
        for w in reversed(self._workers.workers_state()):
            if w.get("bead") == input.target or w.get("role") == input.target:
                return ResolveLogResponse(path=w["log"])
        return ResolveLogResponse(path=None)

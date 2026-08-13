import os
from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.work import worker_log_filename


@dataclass(frozen=True)
class ResolveLogInput:
    target: str


@dataclass(frozen=True)
class ResolveLogResponse:
    path: Optional[str]


class ResolveLogUseCase:
    def __init__(self, store, workers, config):
        self._store = store
        self._workers = workers
        self._config = config

    def execute(self, input: ResolveLogInput) -> ResolveLogResponse:
        if input.target == "run":
            return ResolveLogResponse(
                path=os.path.join(self._config.data_root(), "logs", "run.log")
            )
        for w in reversed(self._workers.workers_state()):
            if w.get("step") == input.target or w.get("role") == input.target:
                return ResolveLogResponse(path=w["log"])
        try:
            node = self._store.get_node(input.target)
        except KeyError:
            return ResolveLogResponse(path=None)
        if node.role and node.claimed_by:
            candidate = os.path.join(
                self._config.data_root(), "logs", worker_log_filename(node.role, node.claimed_by)
            )
            if os.path.exists(candidate):
                return ResolveLogResponse(path=candidate)
        return ResolveLogResponse(path=None)

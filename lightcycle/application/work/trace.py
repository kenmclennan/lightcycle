import os
from dataclasses import dataclass
from typing import List, Optional

from lightcycle.domain.work import Artifact, Node, worker_log_filename


@dataclass(frozen=True)
class TraceInput:
    item: str


@dataclass(frozen=True)
class TraceNode:
    id: str
    step: Optional[str]
    state: str
    log: Optional[str]
    role: Optional[str]

    def as_dict(self):
        return {
            "id": self.id, "step": self.step, "state": self.state, "log": self.log,
            "role": self.role,
        }


@dataclass(frozen=True)
class TraceResponse:
    item: Node
    artifacts: List[Artifact]
    steps: List[TraceNode]

    def as_dict(self):
        return {
            "item": {"id": self.item.id, "title": self.item.title, "state": self.item.state},
            "artifacts": [a.as_dict() for a in self.artifacts],
            "steps": [t.as_dict() for t in self.steps],
        }


class TraceUseCase:
    def __init__(self, store, workers, config):
        self._store = store
        self._workers = workers
        self._config = config

    def _log_for_step(self, node):
        for w in reversed(self._workers.workers_state()):
            if w.get("step") == node.id:
                return w.get("log")
        if node.role and node.claimed_by:
            candidate = os.path.join(
                self._config.data_root(), "logs", worker_log_filename(node.role, node.claimed_by)
            )
            if os.path.exists(candidate):
                return candidate
        return None

    def execute(self, input: TraceInput) -> TraceResponse:
        item = self._store.get_node(input.item)
        artifacts = self._store.item_artifacts(input.item)
        steps = [
            TraceNode(
                id=kt.id, step=kt.step, state=kt.state, log=self._log_for_step(kt),
                role=kt.role,
            )
            for kt in self._store.children(input.item)
        ]
        return TraceResponse(item=item, artifacts=artifacts, steps=steps)

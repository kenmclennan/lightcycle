import os
from dataclasses import dataclass, field
from typing import List, Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.work import Artifact, Item, worker_log_filename


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
    artifacts: List[Artifact] = field(default_factory=list)

    def as_dict(self):
        return {
            "id": self.id, "step": self.step, "state": self.state, "log": self.log,
            "role": self.role, "artifacts": [a.as_dict() for a in self.artifacts],
        }


@dataclass(frozen=True)
class TraceResponse:
    item: Item
    artifacts: List[Artifact]
    steps: List[TraceNode]

    def as_dict(self):
        return {
            "item": {"id": self.item.id, "title": self.item.title, "state": self.item.state},
            "artifacts": [a.as_dict() for a in self.artifacts],
            "steps": [t.as_dict() for t in self.steps],
        }


class TraceUseCase:
    def __init__(self, store, workers, fs, config):
        self._store = store
        self._workers = workers
        self._fs = fs
        self._config = config

    def _log_for_step(self, node):
        for w in reversed(self._workers.workers_state()):
            if w.step == node.id:
                return w.log
        if node.role and node.claimed_by:
            candidate = os.path.join(
                self._config.data_root(), "logs", worker_log_filename(node.role, node.claimed_by)
            )
            if self._fs.exists(candidate):
                return candidate
        if node.log_path and self._fs.exists(node.log_path):
            return node.log_path
        return None

    def execute(self, input: TraceInput) -> TraceResponse:
        item = self._store.get_node(input.item)
        if item.type == "step":
            raise UseCaseError(
                "lc trace takes an item id; %s is a step of %s" % (input.item, item.item)
            )
        artifacts = self._store.item_artifacts(input.item)
        steps = [
            TraceNode(
                id=kt.id, step=kt.stage, state=kt.state, log=self._log_for_step(kt),
                role=kt.role, artifacts=self._store.item_artifacts(kt.id),
            )
            for kt in self._store.children(input.item)
        ]
        return TraceResponse(item=item, artifacts=artifacts, steps=steps)

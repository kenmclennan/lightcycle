from dataclasses import dataclass
from typing import List, Optional

from lightcycle.domain.work import Artifact, Node


@dataclass(frozen=True)
class TraceInput:
    item: str


@dataclass(frozen=True)
class TraceNode:
    id: str
    step: Optional[str]
    state: str
    log: Optional[str]

    def as_dict(self):
        return {"id": self.id, "step": self.step, "state": self.state, "log": self.log}


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
    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def _log_for_step(self, tid):
        for w in reversed(self._workers.workers_state()):
            if w.get("step") == tid:
                return w.get("log")
        return None

    def execute(self, input: TraceInput) -> TraceResponse:
        item = self._store.get_node(input.item)
        artifacts = self._store.item_artifacts(input.item)
        steps = [
            TraceNode(id=kt.id, step=kt.step, state=kt.state, log=self._log_for_step(kt.id))
            for kt in self._store.children(input.item)
        ]
        return TraceResponse(item=item, artifacts=artifacts, steps=steps)

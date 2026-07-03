from dataclasses import dataclass
from typing import List, Optional

from the_grid.domain.work import Artifact, Task


@dataclass(frozen=True)
class TraceInput:
    story: str


@dataclass(frozen=True)
class TraceTask:
    id: str
    step: Optional[str]
    status: str
    log: Optional[str]

    def as_dict(self):
        return {"id": self.id, "step": self.step, "status": self.status, "log": self.log}


@dataclass(frozen=True)
class TraceResponse:
    story: Task
    artifacts: List[Artifact]
    tasks: List[TraceTask]

    def as_dict(self):
        return {
            "story": {"id": self.story.id, "title": self.story.title, "status": self.story.status},
            "artifacts": [a.as_dict() for a in self.artifacts],
            "tasks": [t.as_dict() for t in self.tasks],
        }


class TraceUseCase:
    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def _log_for_task(self, tid):
        for w in reversed(self._workers.workers_state()):
            if w.get("task") == tid:
                return w.get("log")
        return None

    def execute(self, input: TraceInput) -> TraceResponse:
        story = self._store.get_task(input.story)
        artifacts = self._store.story_artifacts(input.story)
        tasks = [
            TraceTask(id=kt.id, step=kt.step, status=kt.status, log=self._log_for_task(kt.id))
            for kt in self._store.children(input.story)
        ]
        return TraceResponse(story=story, artifacts=artifacts, tasks=tasks)

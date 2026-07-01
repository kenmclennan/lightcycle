"""Trace: a story end to end - its artifacts, child tasks, and each task's log."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TraceInput:
    story: str


@dataclass(frozen=True)
class TraceResponse:
    view: dict


class TraceUseCase:

    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def _log_for_bead(self, bid):
        for w in reversed(self._workers.workers_state()):
            if w.get("bead") == bid:
                return w.get("log")
        return None

    def execute(self, input: TraceInput) -> TraceResponse:
        story = self._store.get_task(input.story)
        arts = [a.as_dict() for a in self._store.story_artifacts(input.story)]
        tasks = []
        for kt in self._store.children(input.story):
            tasks.append({"id": kt.id, "step": kt.step, "status": kt.status,
                          "log": self._log_for_bead(kt.id)})
        return TraceResponse(view={
            "story": {"id": story.id, "title": story.title, "status": story.status},
            "artifacts": arts, "tasks": tasks})

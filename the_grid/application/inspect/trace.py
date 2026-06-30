"""Trace: a story end to end - its artifacts, child tasks, and each task's log."""


class Trace:

    def __init__(self, store, workers):
        self._store = store
        self._workers = workers

    def _log_for_bead(self, bid):
        for w in reversed(self._workers.workers_state()):
            if w.get("bead") == bid:
                return w.get("log")
        return None

    def execute(self, story_id):
        story = self._store.get_task(story_id)
        arts = [a.as_dict() for a in self._store.story_artifacts(story_id)]
        tasks = []
        for kt in self._store.children(story_id):
            tasks.append({"id": kt.id, "step": kt.step, "status": kt.status,
                          "log": self._log_for_bead(kt.id)})
        return {"story": {"id": story.id, "title": story.title, "status": story.status},
                "artifacts": arts, "tasks": tasks}

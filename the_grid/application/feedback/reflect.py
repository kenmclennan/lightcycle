"""Reflect: record freeform feedback on the task that produced it (for the retro)."""
import json

from the_grid.domain.feedback import Reflection


class Reflect:

    def __init__(self, store, fs):
        self._store = store
        self._fs = fs

    def _spec_hash(self, tid):
        t = self._store.get_task(tid)
        story = t.parent or tid
        spec = next((a.value for a in self._store.story_artifacts(story)
                     if a.type == "spec"), None)
        data = self._fs.read_bytes(spec)
        return Reflection.spec_hash_of(data) if data is not None else "unknown"

    def execute(self, tid, feedback=""):
        reflection = Reflection.create(tid, feedback, self._spec_hash(tid))
        self._store.add_artifact(tid, "reflection", json.dumps(reflection.as_dict()))
        return reflection

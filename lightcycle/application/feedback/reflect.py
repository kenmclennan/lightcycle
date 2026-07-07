import json
from dataclasses import dataclass

from lightcycle.domain.feedback import Reflection


@dataclass(frozen=True)
class ReflectInput:
    task: str
    feedback: str = ""


@dataclass(frozen=True)
class ReflectResponse:
    reflection: Reflection


class ReflectUseCase:
    def __init__(self, store, fs):
        self._store = store
        self._fs = fs

    def _spec_hash(self, tid):
        t = self._store.get_task(tid)
        story = t.parent or tid
        spec = next((a.value for a in self._store.story_artifacts(story) if a.type == "spec"), None)
        data = self._fs.read_bytes(spec)
        return Reflection.spec_hash_of(data) if data is not None else "unknown"

    def execute(self, input: ReflectInput) -> ReflectResponse:
        reflection = Reflection.create(input.task, input.feedback, self._spec_hash(input.task))
        self._store.add_artifact(input.task, "reflection", json.dumps(reflection.as_dict()))
        return ReflectResponse(reflection=reflection)

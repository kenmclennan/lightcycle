import json
from dataclasses import dataclass

from lightcycle.domain.feedback import Reflection


@dataclass(frozen=True)
class ReflectInput:
    step: str
    feedback: str = ""


@dataclass(frozen=True)
class ReflectResponse:
    reflection: Reflection


class ReflectUseCase:
    def __init__(self, store, fs):
        self._store = store
        self._fs = fs

    def _spec_hash(self, tid):
        t = self._store.get_node(tid)
        item = t.parent or tid
        spec = next((a.value for a in self._store.item_artifacts(item) if a.type == "spec"), None)
        data = self._fs.read_bytes(spec)
        return Reflection.spec_hash_of(data) if data is not None else "unknown"

    def execute(self, input: ReflectInput) -> ReflectResponse:
        reflection = Reflection.create(input.step, input.feedback, self._spec_hash(input.step))
        self._store.add_artifact(input.step, "reflection", json.dumps(reflection.as_dict()))
        return ReflectResponse(reflection=reflection)

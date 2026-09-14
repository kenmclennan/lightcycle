import json
import os
from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.feedback import Reflection


@dataclass(frozen=True)
class ReflectInput:
    step: str
    feedback: str = ""


@dataclass(frozen=True)
class ReflectResponse:
    reflection: Reflection


class ReflectUseCase:
    def __init__(self, store, fs, worktrees):
        self._store = store
        self._fs = fs
        self._worktrees = worktrees

    def _spec_hash(self, tid):
        t = self._store.get_node(tid)
        item = t.item or tid
        spec = next(
            (a.value for a in self._store.item_artifacts(item) if a.kind == "filepath"), None
        )
        if spec is None:
            return "unknown"
        path = spec
        if not os.path.isabs(spec):
            try:
                path = os.path.join(self._worktrees.specs_path(), spec)
            except UseCaseError:
                return "unknown"
        data = self._fs.read_bytes(path)
        return Reflection.spec_hash_of(data) if data is not None else "unknown"

    def execute(self, input: ReflectInput) -> ReflectResponse:
        reflection = Reflection.create(input.step, input.feedback, self._spec_hash(input.step))
        self._store.add_artifact(
            input.step, "reflection", json.dumps(reflection.as_dict()), internal=True
        )
        return ReflectResponse(reflection=reflection)

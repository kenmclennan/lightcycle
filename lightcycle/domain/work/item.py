from dataclasses import dataclass
from typing import Tuple

from lightcycle.domain.work.artifact import Artifact


@dataclass(frozen=True)
class Item:
    id: str
    artifacts: Tuple[Artifact, ...] = ()

    def artifact_of(self, atype, label=None):
        if label is None:
            for a in self.artifacts:
                if a.type == atype:
                    return a.value
            return None
        exact = next(
            (a.value for a in self.artifacts if a.type == atype and a.label == label), None
        )
        if exact is not None:
            return exact
        return next(
            (a.value for a in self.artifacts if a.type == atype and a.label is None), None
        )

    def repo(self):
        return self.artifact_of("repo")

    def present_types(self):
        return {a.type for a in self.artifacts}

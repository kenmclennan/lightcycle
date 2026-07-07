from dataclasses import dataclass
from typing import Tuple

from lightcycle.domain.work.artifact import Artifact


@dataclass(frozen=True)
class Item:
    id: str
    artifacts: Tuple[Artifact, ...] = ()

    def artifact_of(self, atype):
        for a in self.artifacts:
            if a.type == atype:
                return a.value
        return None

    def repo(self, default):
        return self.artifact_of("repo") or default

    def branch(self):
        return self.artifact_of("branch")

    def present_types(self):
        return {a.type for a in self.artifacts}

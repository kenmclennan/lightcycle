from dataclasses import dataclass
from typing import List

from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.node import Node


@dataclass(frozen=True)
class NodeView:
    step: Node
    item_artifacts: List[Artifact]

    def as_dict(self) -> dict:
        d = self.step.as_dict()
        d["item_artifacts"] = [a.as_dict() for a in self.item_artifacts]
        return d

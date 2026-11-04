from dataclasses import dataclass
from typing import List, Optional

from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.step import Step


@dataclass(frozen=True)
class NodeView:
    step: Step
    item_artifacts: List[Artifact]
    stacks_on: Optional[str] = None

    def as_dict(self) -> dict:
        d = self.step.as_dict()
        d["item_artifacts"] = [a.as_dict() for a in self.item_artifacts]
        return d

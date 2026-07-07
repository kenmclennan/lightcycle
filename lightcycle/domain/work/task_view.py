from dataclasses import dataclass
from typing import List

from lightcycle.domain.work.artifact import Artifact
from lightcycle.domain.work.task import Task


@dataclass(frozen=True)
class TaskView:
    task: Task
    story_artifacts: List[Artifact]

    def as_dict(self) -> dict:
        d = self.task.as_dict()
        d["story_artifacts"] = [a.as_dict() for a in self.story_artifacts]
        return d

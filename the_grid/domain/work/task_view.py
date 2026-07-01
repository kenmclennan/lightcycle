"""TaskView: a task (or story) with its story's artifacts, for display (a value object)."""
from dataclasses import dataclass
from typing import List

from the_grid.domain.work.artifact import Artifact
from the_grid.domain.work.task import Task


@dataclass(frozen=True)
class TaskView:
    task: Task
    story_artifacts: List[Artifact]

    def as_dict(self) -> dict:
        d = self.task.as_dict()
        d["story_artifacts"] = [a.as_dict() for a in self.story_artifacts]
        return d

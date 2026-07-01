"""Transition: the flow edge taken for an outcome (a value object)."""
import re
from dataclasses import dataclass

from the_grid.domain.work import TaskSpec


@dataclass(frozen=True)
class Transition:
    from_step: str
    outcome: str
    to_step: str
    to_role: str

    def next_task_spec(self, task) -> TaskSpec:
        title = re.sub(r"^[a-z-]+:\s*", "", task.title)
        return TaskSpec(
            title="%s: %s" % (self.to_step, title),
            step=self.to_step,
            role=self.to_role,
            parent=task.parent,
            deps=(task.id,),
        )

    def forward_note(self, text: str) -> str:
        return "from %s (%s): %s" % (self.from_step, self.outcome, text)

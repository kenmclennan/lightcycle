import re
from dataclasses import dataclass

from lightcycle.domain.work import NodeSpec


@dataclass(frozen=True)
class Transition:
    from_step: str
    outcome: str
    to_step: str
    to_role: str

    def next_step_spec(self, step) -> NodeSpec:
        title = re.sub(r"^[a-z-]+:\s*", "", step.title)
        return NodeSpec(
            title="%s: %s" % (self.to_step, title),
            step=self.to_step,
            role=self.to_role,
            parent=step.parent,
            deps=(step.id,),
        )

    def forward_note(self, text: str) -> str:
        return "from %s (%s): %s" % (self.from_step, self.outcome, text)

from dataclasses import dataclass

from lightcycle.domain.work import NodeSpec


@dataclass(frozen=True)
class Transition:
    from_stage: str
    outcome: str
    to_stage: str
    to_role: str
    to_terminal: bool = False

    def next_step_spec(self, step) -> NodeSpec:
        return NodeSpec(
            step=self.to_stage,
            role=self.to_role,
            parent=step.item,
            deps=(step.id,),
        )

    def forward_note(self, text: str) -> str:
        return "from %s (%s): %s" % (self.from_stage, self.outcome, text)

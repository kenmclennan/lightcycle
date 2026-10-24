from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.flow.hooks import Cap
from lightcycle.domain.work import NodeSpec


@dataclass(frozen=True)
class Escalation:
    cap: Cap
    count: int
    limit: int


@dataclass(frozen=True)
class Transition:
    from_stage: str
    outcome: str
    to_stage: str
    to_role: str
    to_terminal: bool = False
    escalation: Optional[Escalation] = None

    def next_step_spec(self, step) -> NodeSpec:
        return NodeSpec(
            stage=self.to_stage,
            role=self.to_role,
            item=step.item,
            deps=(step.id,),
            previous=step.id,
        )


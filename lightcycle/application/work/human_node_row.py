from dataclasses import dataclass
from typing import List, Optional

from lightcycle.domain.work import Step


@dataclass(frozen=True)
class HumanNodeRow:
    kind: str
    outcomes: List[str]
    step: Step
    project: Optional[str] = None
    description: Optional[str] = None
    artifacts: tuple = ()
    pr: Optional[str] = None

from dataclasses import dataclass
from typing import List, Optional

from lightcycle.domain.work import Step


@dataclass(frozen=True)
class HumanNodeRow:
    kind: str
    outcomes: List[str]
    step: Step
    project: Optional[str] = None
    repo: Optional[str] = None
    description: Optional[str] = None
    artifacts: tuple = ()
    pr: Optional[str] = None
    title: Optional[str] = None
    behind: Optional[str] = None
    slice: int = 0
    slice_name: Optional[str] = None
    item_title: Optional[str] = None

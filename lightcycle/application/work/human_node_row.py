from dataclasses import dataclass
from typing import List, Optional

from lightcycle.domain.work import Node


@dataclass(frozen=True)
class HumanNodeRow:
    kind: str
    outcomes: List[str]
    step: Node
    project: Optional[str] = None
    pr: Optional[str] = None

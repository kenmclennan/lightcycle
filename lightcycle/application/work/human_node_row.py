from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import Node


@dataclass(frozen=True)
class HumanNodeRow:
    kind: str
    outcomes: List[str]
    step: Node

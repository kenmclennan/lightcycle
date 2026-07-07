from dataclasses import dataclass
from typing import List

from lightcycle.domain.work import Task


@dataclass(frozen=True)
class HumanTaskRow:
    kind: str
    outcomes: List[str]
    task: Task

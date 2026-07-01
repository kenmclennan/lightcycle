"""HumanTaskRow: a human-facing task with its classification (a response row)."""
from dataclasses import dataclass
from typing import List

from the_grid.domain.work import Task


@dataclass(frozen=True)
class HumanTaskRow:
    kind: str
    outcomes: List[str]
    task: Task

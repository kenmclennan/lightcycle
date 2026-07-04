from dataclasses import dataclass, field
from typing import Dict, List, Optional

from the_grid.domain.work.artifact import Artifact


@dataclass(frozen=True)
class MigratedTask:
    id: str
    type: Optional[str]
    title: str = ""
    status: str = "open"
    parent: Optional[str] = None
    role: Optional[str] = None
    step: Optional[str] = None
    project: Optional[str] = None
    goal: Optional[str] = None
    attention: bool = False
    assignee: Optional[str] = None
    notes: Optional[str] = None
    outcome: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    since: Optional[str] = None
    fired_at: Optional[str] = None
    closed_at: Optional[str] = None
    created_at: Optional[str] = None


def seed_counters(tasks: List[MigratedTask], shortcode: str) -> Dict[str, int]:
    max_suffix: Dict[str, int] = {}

    def _bump(namespace, suffix_str):
        if not suffix_str.isdigit():
            return
        n = int(suffix_str)
        if n >= max_suffix.get(namespace, 0):
            max_suffix[namespace] = n

    for t in tasks:
        if t.parent:
            if t.id.startswith(t.parent + "."):
                _bump(t.parent, t.id[len(t.parent) + 1:])
        else:
            prefix = shortcode + "-"
            if t.id.startswith(prefix):
                _bump(shortcode, t.id[len(prefix):])

    return {namespace: n + 1 for namespace, n in max_suffix.items()}

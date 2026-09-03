from dataclasses import dataclass
from typing import Optional


class RunState:
    OPEN = "open"
    MERGED = "merged"
    ABANDONED = "abandoned"


def run_id(pass_id: str, phase: Optional[str]) -> str:
    return "%s.%s" % (pass_id, phase or "-")


@dataclass(frozen=True)
class PhaseRun:
    id: str
    item: str
    pass_id: str
    phase: Optional[str] = None
    branch: Optional[str] = None
    pr: Optional[str] = None
    content_pin: Optional[str] = None
    comments_dispatched_through: Optional[str] = None
    comments_handled_through: Optional[str] = None
    state: str = RunState.OPEN
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.state == RunState.OPEN

    def as_dict(self) -> dict:
        return {
            "id": self.id, "item": self.item, "pass_id": self.pass_id, "phase": self.phase,
            "branch": self.branch, "pr": self.pr, "content_pin": self.content_pin,
            "state": self.state, "opened_at": self.opened_at, "closed_at": self.closed_at,
        }

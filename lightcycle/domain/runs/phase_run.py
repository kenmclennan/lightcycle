import re
from dataclasses import dataclass
from typing import Optional


class RunState:
    OPEN = "open"
    MERGED = "merged"
    ABANDONED = "abandoned"


_ROUND_SUFFIX = re.compile(r"\.r(\d+)$")


def run_id(pass_id: str, phase: Optional[str], round: int = 1) -> str:
    base = "%s.%s" % (pass_id, phase or "-")
    return base if round == 1 else "%s.r%d" % (base, round)


def run_round(rid: str) -> int:
    m = _ROUND_SUFFIX.search(rid)
    return int(m.group(1)) if m else 1


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

    @property
    def round(self) -> int:
        return run_round(self.id)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "item": self.item, "pass_id": self.pass_id, "pass": self.pass_id,
            "phase": self.phase,
            "branch": self.branch, "pr": self.pr, "content_pin": self.content_pin,
            "comments_dispatched_through": self.comments_dispatched_through,
            "comments_handled_through": self.comments_handled_through,
            "state": self.state, "opened_at": self.opened_at, "closed_at": self.closed_at,
        }

from dataclasses import dataclass
from typing import Optional


def pass_id(item: str, n: int) -> str:
    return "%s.p%d" % (item, n)


def pass_number(pid: Optional[str]) -> int:
    return int(pid.rsplit(".p", 1)[-1]) if pid and ".p" in pid else 1


@dataclass(frozen=True)
class Pass:
    id: str
    item: str
    n: int
    state: str = "open"
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    def as_dict(self) -> dict:
        return {
            "id": self.id, "item": self.item, "n": self.n, "state": self.state,
            "opened_at": self.opened_at, "closed_at": self.closed_at,
        }

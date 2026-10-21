from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GithubBudget:
    limit: int
    remaining: int
    reset: float
    read_at: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset": self.reset,
            "read_at": self.read_at,
        }


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def github_budget_from_state(state):
    if not isinstance(state, dict):
        return None
    values = [state.get(k) for k in ("limit", "remaining", "reset")]
    if not all(_is_number(v) for v in values):
        return None
    read_at = state.get("read_at")
    return GithubBudget(
        limit=int(values[0]), remaining=int(values[1]), reset=values[2],
        read_at=read_at if _is_number(read_at) else None,
    )


def github_budget_low(budget, reserve, now):
    if budget is None:
        return False
    return now < budget.reset and budget.remaining < reserve

from dataclasses import dataclass


@dataclass(frozen=True)
class GithubBudget:
    limit: int
    remaining: int
    reset: float


def github_budget_from_state(state):
    if not isinstance(state, dict):
        return None
    values = [state.get(k) for k in ("limit", "remaining", "reset")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return None
    return GithubBudget(limit=int(values[0]), remaining=int(values[1]), reset=values[2])


def github_budget_low(budget, reserve, now):
    if budget is None:
        return False
    return now < budget.reset and budget.remaining < reserve

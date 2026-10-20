from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.pool import github_budget_from_state, github_budget_low


@dataclass(frozen=True)
class GithubBudgetReading:
    known: bool
    limit: Optional[int]
    remaining: Optional[int]
    reset: Optional[float]
    reserve: int
    low: bool


@dataclass(frozen=True)
class GithubBudgetState:
    reading: GithubBudgetReading
    opened: bool
    closed: bool


class GithubBudgetUseCase:
    def __init__(self, status, flow, config, clock):
        self._status = status
        self._flow = flow
        self._config = config
        self._clock = clock
        config.github_reserve_calls()

    def reading(self) -> GithubBudgetReading:
        reserve = self._config.github_reserve_calls()
        budget = github_budget_from_state(self._status.load())
        if budget is None:
            return GithubBudgetReading(False, None, None, None, reserve, False)
        return GithubBudgetReading(
            True, budget.limit, budget.remaining, budget.reset, reserve,
            github_budget_low(budget, reserve, self._clock()),
        )

    def held(self, steps):
        if not self.reading().low:
            return frozenset()
        return frozenset(s.id for s in steps if self._flow.is_github_heavy(s))

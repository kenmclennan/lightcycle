from abc import ABC, abstractmethod
from typing import Optional

from lightcycle.domain.pool import GithubBudget


class GithubBudgetStatusPort(ABC):
    @abstractmethod
    def load(self) -> Optional[GithubBudget]:
        pass

    @abstractmethod
    def save(self, state: GithubBudget) -> None:
        pass

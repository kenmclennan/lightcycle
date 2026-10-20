from abc import ABC, abstractmethod


class GithubBudgetStatusPort(ABC):
    @abstractmethod
    def load(self):
        pass

    @abstractmethod
    def save(self, state):
        pass

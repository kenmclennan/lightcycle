from lightcycle.ports.github_budget_status import GithubBudgetStatusPort


class FakeGithubBudgetStatus(GithubBudgetStatusPort):
    def __init__(self, state=None):
        self._state = state
        self.saves = []

    def load(self):
        return self._state

    def save(self, state):
        self._state = state
        self.saves.append(state)

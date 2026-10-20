from lightcycle.ports.github_budget_status import GithubBudgetStatusPort


class FakeGithubBudgetStatus(GithubBudgetStatusPort):
    def __init__(self, state=None):
        self._state = state if state is not None else {}
        self.saves = []

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)
        self.saves.append(dict(state))

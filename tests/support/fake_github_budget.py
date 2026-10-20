from lightcycle.application.pool.github_budget import GithubBudgetReading


class FakeGithubBudget:
    def __init__(self, low=False, remaining=None, limit=5000, reset=None, reserve=750, heavy=()):
        self._low = low
        self._heavy = set(heavy)
        known = remaining is not None
        self._reading = GithubBudgetReading(known, limit if known else None, remaining, reset, reserve, low)
        self.held_calls = []

    def set_low(self, low):
        self._low = low
        self._reading = GithubBudgetReading(
            self._reading.known, self._reading.limit, self._reading.remaining,
            self._reading.reset, self._reading.reserve, low)

    def reading(self):
        return self._reading

    def held(self, steps):
        self.held_calls.append([s.id for s in steps])
        if not self._low:
            return frozenset()
        return frozenset(s.id for s in steps if s.id in self._heavy or s.stage in self._heavy)

"""List stories shipped in a period (today, yesterday, a date, a range)."""
from the_grid.domain import feedback as cfeedback


class Worklog:

    def __init__(self, store):
        self._store = store

    def execute(self, period_args, today, tz):
        period = cfeedback.Period.resolve(period_args, today)
        return cfeedback.Worklog(self._store.closed_stories()).entries(period, tz)

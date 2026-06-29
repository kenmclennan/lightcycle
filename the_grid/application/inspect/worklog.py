"""List stories shipped in a period (today, yesterday, a date, a range)."""
from the_grid.core import worklog as cworklog


class Worklog:

    def __init__(self, store):
        self._store = store

    def execute(self, period_args, today):
        start, end = cworklog.resolve_period(period_args, today)
        return cworklog.worklog(self._store.closed_stories(), start, end)

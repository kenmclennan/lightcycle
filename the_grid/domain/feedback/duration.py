import datetime

from the_grid.domain.work.status import Status


class Duration:
    def __init__(self, transitions):
        self._transitions = list(transitions)

    def elapsed(self):
        claimed = self._first(Status.IN_PROGRESS)
        finished = self._last(Status.DONE)
        if claimed is None or finished is None:
            return None
        return self._parse(finished) - self._parse(claimed)

    def _first(self, status):
        for s, ts in self._transitions:
            if s == status:
                return ts
        return None

    def _last(self, status):
        for s, ts in reversed(self._transitions):
            if s == status:
                return ts
        return None

    @staticmethod
    def _parse(ts):
        return datetime.datetime.fromisoformat(ts)

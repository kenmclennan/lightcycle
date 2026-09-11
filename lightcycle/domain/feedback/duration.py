from lightcycle.domain.work.state import ALIASES, State
from lightcycle.domain.work.timestamp import parse_timestamp


class Duration:
    def __init__(self, transitions):
        self._transitions = list(transitions)

    def elapsed(self):
        claimed = self._first(State.RUNNING)
        finished = self._last(State.DONE)
        if claimed is None or finished is None:
            return None
        return self._parse(finished) - self._parse(claimed)

    def elapsed_since_claim(self, now):
        claimed = self._first(State.RUNNING)
        if claimed is None or self._last(State.DONE) is not None:
            return None
        return self._parse(now) - self._parse(claimed)

    def elapsed_since_last_claim(self, now):
        claimed = self._last(State.RUNNING)
        if claimed is None:
            return None
        finished = self._last(State.DONE)
        if finished is not None and self._parse(finished) >= self._parse(claimed):
            return self._parse(finished) - self._parse(claimed)
        return self._parse(now) - self._parse(claimed)

    def last_release(self):
        return self._last(State.WAITING)

    @classmethod
    def earliest_claim(cls, histories):
        claims = [
            ts for transitions in histories
            for state, ts in transitions
            if (state == State.RUNNING or state == ALIASES[State.RUNNING]) and ts
        ]
        return min(claims) if claims else None

    def _first(self, status):
        legacy = ALIASES.get(status)
        for s, ts in self._transitions:
            if s == status or s == legacy:
                return ts
        return None

    def _last(self, status):
        legacy = ALIASES.get(status)
        for s, ts in reversed(self._transitions):
            if s == status or s == legacy:
                return ts
        return None

    @staticmethod
    def _parse(ts):
        return parse_timestamp(ts)

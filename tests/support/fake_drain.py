from lightcycle.ports.drain import PoolDrainPort


class FakeDrain(PoolDrainPort):
    def __init__(self, requested=False, at=None):
        self._requested = requested
        self._at = at
        self.request_calls = 0

    def request(self):
        self.request_calls += 1
        self._requested = True

    def requested(self):
        return self._requested

    def requested_at(self):
        return self._at if self._requested else None

    def clear(self):
        self._requested = False

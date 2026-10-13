from lightcycle.ports.drain import PoolDrainPort


class FakeDrain(PoolDrainPort):
    def __init__(self, requested=False):
        self._requested = requested
        self.request_calls = 0

    def request(self):
        self.request_calls += 1
        self._requested = True

    def requested(self):
        return self._requested

    def clear(self):
        self._requested = False

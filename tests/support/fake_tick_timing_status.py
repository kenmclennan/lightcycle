from lightcycle.ports.tick_timing_status import TickTimingStatusPort


class FakeTickTimingStatus(TickTimingStatusPort):
    def __init__(self, timing=None):
        self._timing = timing
        self.saves = []

    def load(self):
        return self._timing

    def save(self, timing):
        self._timing = timing
        self.saves.append(timing)

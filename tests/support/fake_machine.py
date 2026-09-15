from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort


class FakeMachine(MachinePort):
    def __init__(self, headroom=None, rss=None):
        self._headroom = headroom if headroom is not None else MachineHeadroom(None, None)
        self._rss = rss

    def headroom(self, workers):
        return self._headroom

    def self_rss(self):
        return self._rss

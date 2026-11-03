from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort


class FakeMachine(MachinePort):
    def __init__(self, headroom=None, rss=None, cwd_pids=None):
        self._headroom = headroom if headroom is not None else MachineHeadroom(pool_share=None)
        self._rss = rss
        self._cwd_pids = cwd_pids or {}

    def headroom(self, workers):
        return self._headroom

    def self_rss(self):
        return self._rss

    def cwd_pids_under(self, root):
        return {
            path: list(pids) for path, pids in self._cwd_pids.items()
            if path.startswith(root + "/")
        }

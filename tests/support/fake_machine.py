from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort


class FakeMachine(MachinePort):
    def __init__(self, headroom=None, rss=None, cwd_pids=None):
        self._headroom = headroom if headroom is not None else MachineHeadroom(pool_share=None)
        self._rss = rss
        self._cwd_pids = cwd_pids or {}
        self.cwd_calls = []

    def headroom(self, workers):
        return self._headroom

    def self_rss(self):
        return self._rss

    def cwd_pids_under(self, root):
        self.cwd_calls.append(root)
        table = self._cwd_pids
        if isinstance(table, list):
            table = table[min(len(self.cwd_calls), len(table)) - 1]
        return {
            path: list(pids) for path, pids in table.items()
            if path.startswith(root + "/")
        }

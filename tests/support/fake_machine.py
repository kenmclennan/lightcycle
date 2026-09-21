from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.ports.machine import MachinePort


class FakeMachine(MachinePort):
    def __init__(self, headroom=None, rss=None, worktree_pids=None):
        self._headroom = headroom if headroom is not None else MachineHeadroom(pool_share=None)
        self._rss = rss
        self._worktree_pids = worktree_pids or {}

    def headroom(self, workers):
        return self._headroom

    def self_rss(self):
        return self._rss

    def worktree_pids(self, path):
        return self._worktree_pids.get(path, [])

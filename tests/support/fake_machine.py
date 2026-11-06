from lightcycle.domain.pool.machine_headroom import MachineHeadroom
from lightcycle.domain.health.gh_tooling import GhTooling
from lightcycle.ports.machine import MachinePort


class FakeMachine(MachinePort):
    def __init__(self, headroom=None, rss=None, cwd_pids=None, gh_tooling=None):
        self._headroom = headroom if headroom is not None else MachineHeadroom(pool_share=None)
        self._rss = rss
        self._cwd_pids = cwd_pids or {}
        self.cwd_calls = []
        self._gh_tooling = gh_tooling if gh_tooling is not None else GhTooling(
            version_text="gh version 2.103.3 (2026-01-01)\n",
            extensions_text="gh stack\tgithub/gh-stack\tv0.3.0\n",
        )

    def headroom(self, workers):
        return self._headroom

    def gh_tooling(self):
        return self._gh_tooling

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

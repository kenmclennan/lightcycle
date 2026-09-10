from abc import ABC, abstractmethod


class TeardownLedgerPort(ABC):
    @abstractmethod
    def created_worktrees(self):
        pass

    @abstractmethod
    def torn_down_worktrees(self):
        pass

    @abstractmethod
    def created_branches(self):
        pass

    @abstractmethod
    def torn_down_branches(self):
        pass

    @abstractmethod
    def torn_down_remote_branches(self):
        pass

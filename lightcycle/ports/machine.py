from abc import ABC, abstractmethod


class MachinePort(ABC):
    @abstractmethod
    def headroom(self, workers):
        pass

    @abstractmethod
    def self_rss(self):
        pass

    @abstractmethod
    def gh_tooling(self):
        pass

    @abstractmethod
    def signal_pid(self, pid, sig):
        pass

    @abstractmethod
    def cwd_pids_under(self, root):
        pass

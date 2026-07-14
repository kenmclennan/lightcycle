from abc import ABC, abstractmethod


class BackupPort(ABC):
    @abstractmethod
    def list_snapshots(self):
        pass

    @abstractmethod
    def create_snapshot(self, now):
        pass

    @abstractmethod
    def prune(self, keep):
        pass

    @abstractmethod
    def restore(self, name):
        pass

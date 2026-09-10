from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    name: str
    taken_at: float


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

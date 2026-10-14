from abc import ABC, abstractmethod


class GuidanceSyncStatusPort(ABC):
    @abstractmethod
    def load(self):
        pass

    @abstractmethod
    def save(self, state):
        pass

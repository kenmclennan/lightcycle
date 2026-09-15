from abc import ABC, abstractmethod


class MemoryGateStatusPort(ABC):
    @abstractmethod
    def load(self):
        pass

    @abstractmethod
    def save(self, state):
        pass

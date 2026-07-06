from abc import ABC, abstractmethod


class BreakerPort(ABC):
    @abstractmethod
    def load(self):
        pass

    @abstractmethod
    def save(self, state):
        pass

from abc import ABC, abstractmethod


class SpinPort(ABC):
    @abstractmethod
    def load(self):
        pass

    @abstractmethod
    def save(self, state):
        pass

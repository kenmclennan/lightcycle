from abc import ABC, abstractmethod


class ConfigReloadStatusPort(ABC):
    @abstractmethod
    def load(self):
        pass

    @abstractmethod
    def save(self, state):
        pass

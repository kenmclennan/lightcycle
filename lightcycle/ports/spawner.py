from abc import ABC, abstractmethod


class SpawnerPort(ABC):
    @abstractmethod
    def spawn_worker(self, role):
        pass

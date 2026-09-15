from abc import ABC, abstractmethod


class MachinePort(ABC):
    @abstractmethod
    def headroom(self, workers):
        pass

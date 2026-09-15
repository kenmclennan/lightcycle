from abc import ABC, abstractmethod


class MachinePort(ABC):
    @abstractmethod
    def headroom(self, workers):
        pass

    @abstractmethod
    def self_rss(self):
        pass

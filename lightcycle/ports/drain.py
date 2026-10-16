from abc import ABC, abstractmethod


class PoolDrainPort(ABC):
    @abstractmethod
    def request(self):
        pass

    @abstractmethod
    def requested(self):
        pass

    @abstractmethod
    def requested_at(self):
        pass

    @abstractmethod
    def clear(self):
        pass

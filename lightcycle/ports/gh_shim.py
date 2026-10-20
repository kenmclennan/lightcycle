from abc import ABC, abstractmethod


class GhShimPort(ABC):
    @abstractmethod
    def install(self):
        pass

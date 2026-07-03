from abc import ABC, abstractmethod


class RunLockPort(ABC):
    @abstractmethod
    def acquire(self):
        pass

    @abstractmethod
    def release(self):
        pass

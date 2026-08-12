from abc import ABC, abstractmethod


class RunLockPort(ABC):
    @abstractmethod
    def acquire(self):
        pass

    @abstractmethod
    def release(self):
        pass

    @abstractmethod
    def is_running(self):
        pass

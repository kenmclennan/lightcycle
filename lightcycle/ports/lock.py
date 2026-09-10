from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LockAcquisition:
    acquired: bool
    holder_pid: Optional[int]


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

    @abstractmethod
    def holder_pid(self):
        pass

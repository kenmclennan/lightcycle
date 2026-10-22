from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class StoppedRuns:
    terminated: List[str] = field(default_factory=list)
    killed: List[str] = field(default_factory=list)


class RunGroupsPort(ABC):
    @abstractmethod
    def register(self, label, proc):
        pass

    @abstractmethod
    def release(self, proc):
        pass

    @abstractmethod
    def stop(self, grace_seconds) -> StoppedRuns:
        pass

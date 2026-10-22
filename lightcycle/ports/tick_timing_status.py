from abc import ABC, abstractmethod
from typing import Optional

from lightcycle.domain.pool import TickTiming


class TickTimingStatusPort(ABC):
    @abstractmethod
    def load(self) -> Optional[TickTiming]:
        pass

    @abstractmethod
    def save(self, timing: TickTiming) -> None:
        pass

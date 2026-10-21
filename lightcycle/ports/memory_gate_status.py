from abc import ABC, abstractmethod
from typing import Optional

from lightcycle.domain.pool import MemoryGateState


class MemoryGateStatusPort(ABC):
    @abstractmethod
    def load(self) -> Optional[MemoryGateState]:
        pass

    @abstractmethod
    def save(self, state: MemoryGateState) -> None:
        pass

from abc import ABC, abstractmethod
from typing import Optional

from lightcycle.domain.pool import GuidanceSyncState


class GuidanceSyncStatusPort(ABC):
    @abstractmethod
    def load(self) -> Optional[GuidanceSyncState]:
        pass

    @abstractmethod
    def save(self, state: GuidanceSyncState) -> None:
        pass

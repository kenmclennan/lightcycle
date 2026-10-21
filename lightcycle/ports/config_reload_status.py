from abc import ABC, abstractmethod
from typing import Optional

from lightcycle.domain.pool import ConfigReloadState


class ConfigReloadStatusPort(ABC):
    @abstractmethod
    def load(self) -> Optional[ConfigReloadState]:
        pass

    @abstractmethod
    def save(self, state: ConfigReloadState) -> None:
        pass

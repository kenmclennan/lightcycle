from abc import ABC, abstractmethod


class SleepLedgerPort(ABC):
    @abstractmethod
    def load(self) -> dict:
        pass

    @abstractmethod
    def save(self, state: dict) -> None:
        pass

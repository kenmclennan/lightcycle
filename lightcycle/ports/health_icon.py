from abc import ABC, abstractmethod


class HealthIconPort(ABC):
    @abstractmethod
    def transmit(self, image_id: int, png: bytes, columns: int) -> None:
        pass

    @abstractmethod
    def delete_all(self) -> None:
        pass

"""SpawnerPort: the abstract worker-spawning interface the application depends on."""
from abc import ABC, abstractmethod


class SpawnerPort(ABC):

    @abstractmethod
    def spawn_worker(self, role):
        """Spawn an ephemeral worker for role and return its spawn id."""

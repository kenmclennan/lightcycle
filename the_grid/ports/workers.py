"""WorkersPort: the abstract worker-registry interface the application depends on."""
from abc import ABC, abstractmethod


class WorkersPort(ABC):

    @abstractmethod
    def workers_state(self):
        """Return the current workers registry."""

    @abstractmethod
    def write_workers(self, workers):
        """Persist the workers registry."""

    @abstractmethod
    def pid_alive(self, pid):
        """Return True if pid is a live process."""

    @abstractmethod
    def prune_workers(self, keep_dead=None):
        """Remove dead workers from the registry; return the pruned registry."""

    @abstractmethod
    def stamp_bead(self, spawnid, bead):
        """Record the bead a worker is running against its spawn id."""

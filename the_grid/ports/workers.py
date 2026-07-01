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
    def set_task(self, spawnid, task):
        """Record the task a worker has claimed against its spawn id."""

from abc import ABC, abstractmethod


class WorkersPort(ABC):
    @abstractmethod
    def workers_state(self):
        pass

    @abstractmethod
    def write_workers(self, workers):
        pass

    @abstractmethod
    def pid_alive(self, pid):
        pass

    @abstractmethod
    def kill(self, pid):
        pass

    @abstractmethod
    def prune_workers(self, keep_dead=None):
        pass

    @abstractmethod
    def set_task(self, spawnid, task):
        pass

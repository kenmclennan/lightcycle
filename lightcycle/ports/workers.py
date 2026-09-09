from abc import ABC, abstractmethod


class RegistryUnreadable(Exception):
    pass


class WorkersPort(ABC):
    @abstractmethod
    def workers_state(self):
        pass

    @abstractmethod
    def pid_alive(self, pid, started=None):
        pass

    @abstractmethod
    def reap(self):
        pass

    @abstractmethod
    def kill(self, pid):
        pass

    @abstractmethod
    def prune_workers(self, keep_dead=None):
        pass

    @abstractmethod
    def set_step(self, spawnid, step):
        pass

    @abstractmethod
    def step_for(self, spawnid):
        pass

    @abstractmethod
    def mark_checked(self, spawnid):
        pass

    @abstractmethod
    def log_mtime(self, path):
        pass

    @abstractmethod
    def set_pid_started(self, spawnid, pid_started):
        pass

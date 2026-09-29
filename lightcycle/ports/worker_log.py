from abc import ABC, abstractmethod


class WorkerLogPort(ABC):
    @abstractmethod
    def read_from(self, path, offset):
        pass

    @abstractmethod
    def read_from_bounded(self, path, offset, max_bytes):
        pass

    @abstractmethod
    def read_tail(self, path, max_bytes):
        pass

    @abstractmethod
    def iter_lines(self, path):
        pass

    @abstractmethod
    def list_worker_log_files(self, root):
        pass

    @abstractmethod
    def append_run_log(self, text):
        pass

    @abstractmethod
    def log_mtime(self, path):
        pass

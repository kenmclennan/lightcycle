from abc import ABC, abstractmethod


class FsPort(ABC):
    @abstractmethod
    def worktrees_dir(self, root):
        pass

    @abstractmethod
    def store_ready(self):
        pass

    @abstractmethod
    def read_bytes(self, path):
        pass

    @abstractmethod
    def exists(self, path):
        pass

    @abstractmethod
    def is_executable(self, path):
        pass

    @abstractmethod
    def list_dir(self, path):
        pass

    @abstractmethod
    def list_files(self, root):
        pass

    @abstractmethod
    def ensure_logs_dir(self):
        pass

    @abstractmethod
    def ensure_worktrees_ignored(self, git_dir):
        pass

    @abstractmethod
    def write_text(self, path, text):
        pass

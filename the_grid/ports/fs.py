from abc import ABC, abstractmethod


class FsPort(ABC):
    @abstractmethod
    def step_roles(self, project=None):
        pass

    @abstractmethod
    def read_md(self, relpath, project=None):
        pass

    @abstractmethod
    def parse_step(self, role, project=None):
        pass

    @abstractmethod
    def workflow_text(self, name, project=None):
        pass

    @abstractmethod
    def worktrees_dir(self):
        pass

    @abstractmethod
    def store_ready(self):
        pass

    @abstractmethod
    def read_bytes(self, path):
        pass

    @abstractmethod
    def list_dir(self, path):
        pass

    @abstractmethod
    def ensure_logs_dir(self):
        pass

    @abstractmethod
    def ensure_override_dirs(self):
        pass

    @abstractmethod
    def ensure_worktrees_ignored(self):
        pass

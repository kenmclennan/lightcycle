from abc import ABC, abstractmethod


class FsPort(ABC):
    @abstractmethod
    def step_roles(self, root):
        pass

    @abstractmethod
    def read_md(self, relpath, root):
        pass

    @abstractmethod
    def parse_step(self, role, root):
        pass

    @abstractmethod
    def workflow_text(self, name, root):
        pass

    @abstractmethod
    def workflow_names(self, root):
        pass

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
    def list_dir(self, path):
        pass

    @abstractmethod
    def ensure_logs_dir(self):
        pass

    @abstractmethod
    def ensure_worktrees_ignored(self, root):
        pass

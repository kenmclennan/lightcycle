from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HookResult:
    exit_code: Optional[int]
    output: str = ""
    timed_out: bool = False

    @property
    def ok(self):
        return self.exit_code == 0 and not self.timed_out


class LifecycleRunnerPort(ABC):
    @abstractmethod
    def run(self, script_path, cwd, env, timeout):
        pass

    @abstractmethod
    def start(self, key, script_path, cwd, env, timeout):
        pass

    @abstractmethod
    def poll(self, key):
        pass

    @abstractmethod
    def running(self):
        pass

    @abstractmethod
    def last_due(self, key):
        pass

    @abstractmethod
    def record_due(self, key, due):
        pass

    @abstractmethod
    def ensure_data_dir(self, path):
        pass

    @abstractmethod
    def remove_data_dir(self, path):
        pass

    @abstractmethod
    def data_dir_exists(self, path):
        pass

    @abstractmethod
    def list_data_dirs(self, path):
        pass

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScriptResult:
    exit_code: Optional[int]
    stdout: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    log_path: Optional[str] = None


class ScriptRunnerPort(ABC):
    @abstractmethod
    def run(self, script_path, cwd, env, stdin_text, timeout, log_label):
        pass

    @abstractmethod
    def start(self, key, script_path, cwd, env, stdin_text, timeout, log_label):
        pass

    @abstractmethod
    def poll(self, key):
        pass

    @abstractmethod
    def running(self):
        pass

    @abstractmethod
    def orphaned(self):
        pass

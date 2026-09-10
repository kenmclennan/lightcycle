from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StepPrompt:
    meta: dict
    body: str


class WorkflowBundlePort(ABC):
    @abstractmethod
    def step_roles(self, root):
        pass

    @abstractmethod
    def parse_step(self, role, root):
        pass

    @abstractmethod
    def workflow_text(self, name, root):
        pass

    @abstractmethod
    def workflow_meta(self, name, root):
        pass

    @abstractmethod
    def workflow_names(self, root):
        pass

from abc import ABC, abstractmethod
from dataclasses import dataclass


class WorkflowSourceError(Exception):
    pass


@dataclass(frozen=True)
class FetchedBundle:
    manifest: str
    sha: str
    steps: dict
    workflows: dict


@dataclass(frozen=True)
class OriginRegistration:
    url: str
    ref: str
    current: str


class WorkflowSourcePort(ABC):
    @abstractmethod
    def fetch(self, url, ref):
        pass

    @abstractmethod
    def read_manifest(self, checkout_dir):
        pass

    @abstractmethod
    def pin(self, origin, bundle):
        pass

    @abstractmethod
    def has_version(self, origin, sha):
        pass

    @abstractmethod
    def pinned_bundle(self, origin, sha):
        pass

    @abstractmethod
    def current_sha(self, origin):
        pass

    @abstractmethod
    def unresolvable_reason(self, url, ref):
        pass

    @abstractmethod
    def workflow_names(self, origin, sha):
        pass

    @abstractmethod
    def write_registry(self, origin, url, ref, current):
        pass

    @abstractmethod
    def read_registry(self, origin):
        pass

    @abstractmethod
    def list_origins(self):
        pass

    @abstractmethod
    def list_versions(self, origin):
        pass

    @abstractmethod
    def remove_version(self, origin, sha):
        pass

    @abstractmethod
    def remove_origin(self, origin):
        pass

    @abstractmethod
    def resolve_agent(self, role, pin):
        pass

from abc import ABC, abstractmethod


class WorkflowSourcePort(ABC):
    @abstractmethod
    def fetch(self, url, ref):
        pass

    @abstractmethod
    def read_manifest(self, checkout_dir):
        pass

    @abstractmethod
    def materialize(self, origin, sha, checkout_dir):
        pass

    @abstractmethod
    def has_version(self, origin, sha):
        pass

    @abstractmethod
    def bundle_path(self, origin, sha):
        pass

    @abstractmethod
    def current_sha(self, origin):
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
    def cleanup(self, checkout_dir):
        pass

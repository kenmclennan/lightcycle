from abc import ABC, abstractmethod


class UpgradePort(ABC):
    @abstractmethod
    def list_processes(self):
        pass

    @abstractmethod
    def fetch_remote_version(self):
        pass

    @abstractmethod
    def install_upgrade(self):
        pass

    @abstractmethod
    def installed_version(self):
        pass

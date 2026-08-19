from abc import ABC, abstractmethod


class LauncherPort(ABC):
    @abstractmethod
    def open_url(self, url):
        pass

    @abstractmethod
    def open_path(self, path):
        pass

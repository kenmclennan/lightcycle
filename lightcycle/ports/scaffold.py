from abc import ABC, abstractmethod


class ScaffoldPort(ABC):
    @abstractmethod
    def write_text(self, path, content):
        pass

    @abstractmethod
    def make_dir(self, path):
        pass

    @abstractmethod
    def is_dir(self, path):
        pass

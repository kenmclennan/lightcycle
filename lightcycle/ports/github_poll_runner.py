from abc import ABC, abstractmethod


class GithubPollRunnerPort(ABC):
    @abstractmethod
    def start(self, fn) -> bool:
        pass

    @abstractmethod
    def join(self) -> None:
        pass

    @abstractmethod
    def running(self) -> bool:
        pass

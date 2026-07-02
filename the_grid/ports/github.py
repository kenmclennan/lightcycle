"""GitHubEventsPort: abstract interface for querying GitHub PR state."""
from abc import ABC, abstractmethod


class GitHubEventsPort(ABC):

    @abstractmethod
    def is_merged(self, pr: str) -> bool:
        """Return True if the PR (a GitHub PR URL or number) has been merged."""

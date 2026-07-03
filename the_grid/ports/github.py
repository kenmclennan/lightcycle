"""GitHubEventsPort: abstract interface for querying GitHub PR state."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    is_top_level: bool
    path: Optional[str] = None
    line: Optional[int] = None


class GitHubEventsPort(ABC):

    @abstractmethod
    def is_merged(self, pr: str) -> bool:
        """Return True if the PR (a GitHub PR URL or number) has been merged."""

    @abstractmethod
    def is_closed_unmerged(self, pr: str) -> bool:
        """Return True if the PR was closed without merging (state == CLOSED on GitHub)."""

    @abstractmethod
    def last_push_time(self, pr: str) -> float:
        """Return UTC epoch seconds of the last push to the PR's head branch."""

    @abstractmethod
    def is_conflicted(self, pr: str) -> bool:
        """Return True only for definitive conflict (CONFLICTING/DIRTY); False for UNKNOWN."""

    @abstractmethod
    def comments_since(self, pr: str, since: float) -> List[Comment]:
        """Return comments posted on the PR after the given UTC epoch timestamp."""

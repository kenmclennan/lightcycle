from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Union


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    is_top_level: bool
    path: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None
    in_reply_to_id: Optional[str] = None
    created_at: float = 0.0


@dataclass(frozen=True)
class Review:
    author: str
    body: str
    created_at: float = 0.0
    state: str = ""


@dataclass(frozen=True)
class ReadFailure:
    returncode: int
    stderr: str


class GitHubEventsPort(ABC):
    @abstractmethod
    def is_merged(self, pr: str) -> Union[bool, ReadFailure]:
        pass

    @abstractmethod
    def is_closed_unmerged(self, pr: str) -> Union[bool, ReadFailure]:
        pass

    @abstractmethod
    def last_push_time(self, pr: str) -> Union[float, ReadFailure]:
        pass

    @abstractmethod
    def is_conflicted(self, pr: str) -> Union[bool, ReadFailure]:
        """Return True only for definitive conflict (CONFLICTING/DIRTY), False for a
        definitive non-conflicting state, and ReadFailure when the state could not be read."""

    @abstractmethod
    def comments_since(self, pr: str, since: float) -> Union[List[Comment], ReadFailure]:
        pass

    @abstractmethod
    def pull_comments(self, pr: str, since: float) -> Union[List[Comment], ReadFailure]:
        pass

    @abstractmethod
    def reviews(self, pr: str, since: float) -> Union[List[Review], ReadFailure]:
        pass

    @abstractmethod
    def head_sha(self, pr: str) -> Union[str, ReadFailure]:
        pass

    @abstractmethod
    def changed_files(self, pr: str, sha: str) -> Union[frozenset, ReadFailure]:
        pass

    @abstractmethod
    def ci_pending(self, pr: str, sha: str) -> Union[bool, ReadFailure]:
        pass

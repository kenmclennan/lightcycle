from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union


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
    id: Optional[str] = None


@dataclass(frozen=True)
class ReadFailure:
    returncode: int
    stderr: str


@dataclass(frozen=True)
class CheckRun:
    name: str
    status: str
    conclusion: Optional[str]
    url: str = ""


@dataclass(frozen=True)
class PrSync:
    behind: bool
    conflicted: bool
    head_sha: str
    base_key: str


class GitHubEventsPort(ABC):
    @abstractmethod
    def authenticated_login(self) -> Union[str, ReadFailure]:
        pass

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
    def check_runs(self, pr: str, sha: str) -> Union[Tuple[CheckRun, ...], ReadFailure]:
        pass

    @abstractmethod
    def issue_state(self, url: str) -> Union[str, ReadFailure]:
        pass

    @abstractmethod
    def pr_sync_state(self, pr: str) -> Union[PrSync, ReadFailure]:
        pass

    @abstractmethod
    def requires_up_to_date(self, base_key: str) -> Union[bool, ReadFailure]:
        pass

    @abstractmethod
    def update_branch(self, pr: str, expected_head_sha: str) -> Union[None, ReadFailure]:
        pass

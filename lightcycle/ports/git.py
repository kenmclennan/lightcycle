from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


class GitReadError(Exception):
    pass


@dataclass(frozen=True)
class GitOutcome:
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class RestackStep:
    branch: str
    lease_sha: str
    old_base: str
    onto: str
    worktree_path: Optional[str] = None


@dataclass(frozen=True)
class RestackOutcome:
    kind: str
    branch: Optional[str] = None
    files: Tuple[str, ...] = ()
    detail: str = ""
    tips: Dict[str, str] = field(default_factory=dict)


RESTACK_PUSHED = "pushed"
RESTACK_CONFLICT = "conflict"
RESTACK_LEASE_LOST = "lease-lost"
RESTACK_FAILED = "failed"


class GitPort(ABC):
    @abstractmethod
    def add_worktree(self, root, path, branch, base, retries, backoff):
        pass

    @abstractmethod
    def prune_worktrees(self, root):
        pass

    @abstractmethod
    def set_branch_upstream(self, root, branch, remote="origin"):
        pass

    @abstractmethod
    def init_repo(self, root, branch="main"):
        pass

    @abstractmethod
    def is_git_repo(self, root):
        pass

    @abstractmethod
    def is_repo_root(self, root):
        pass

    @abstractmethod
    def remote_url(self, root):
        pass

    @abstractmethod
    def branch_exists(self, root, branch):
        pass

    @abstractmethod
    def remote_branch_exists(self, root, branch):
        pass

    @abstractmethod
    def worktree_base(self, root):
        pass

    @abstractmethod
    def sync_to_origin(self, root):
        pass

    @abstractmethod
    def clone(self, url, dest):
        pass

    @abstractmethod
    def clone_identity(self, identity, dest):
        pass

    @abstractmethod
    def sync_to_default_branch(self, root):
        pass

    @abstractmethod
    def remove_worktree(self, root, path):
        pass

    @abstractmethod
    def delete_branch(self, root, branch):
        pass

    @abstractmethod
    def delete_remote_branch(self, root, branch):
        pass

    @abstractmethod
    def worktree_registered(self, root, path):
        pass

    @abstractmethod
    def has_uncommitted(self, root):
        pass

    @abstractmethod
    def commit_all(self, root, message):
        pass

    @abstractmethod
    def missing_identity(self, root):
        pass

    @abstractmethod
    def has_tracked_changes(self, root):
        pass

    @abstractmethod
    def commit_tracked(self, root, message):
        pass

    @abstractmethod
    def common_dir(self, root):
        pass

    @abstractmethod
    def ref_sha(self, root, ref):
        pass

    @abstractmethod
    def fetch_origin(self, root):
        pass

    @abstractmethod
    def default_ref(self, root):
        pass

    @abstractmethod
    def list_files_at(self, root, ref):
        pass

    @abstractmethod
    def read_file_at(self, root, ref, path):
        pass

    @abstractmethod
    def added_at(self, root, ref, path):
        pass

    @abstractmethod
    def last_change_at(self, root, ref, path):
        pass

    @abstractmethod
    def commits_touching(self, root, ref, path, limit):
        pass

    @abstractmethod
    def changed_paths(self, root, base):
        pass

    @abstractmethod
    def uncommitted_paths(self, root):
        pass

    @abstractmethod
    def commits_beyond(self, root, base, branch):
        pass

    @abstractmethod
    def merge_base(self, root, a, b):
        pass

    @abstractmethod
    def restack(self, root, steps):
        pass

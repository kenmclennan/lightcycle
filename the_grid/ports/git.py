"""GitPort: the abstract git interface the application depends on."""
from abc import ABC, abstractmethod


class GitPort(ABC):

    @abstractmethod
    def git(self, root, *args):
        """Run a git command in root and return its stdout."""

    @abstractmethod
    def git_ok(self, root, *args):
        """Run a git command in root and return True on success."""

    @abstractmethod
    def is_git_repo(self, root):
        """Return True if root is a git working tree."""

    @abstractmethod
    def branch_exists(self, root, branch):
        """Return True if branch exists in root."""

    @abstractmethod
    def worktree_base(self, root):
        """Return the main worktree path for root."""

    @abstractmethod
    def remove_worktree(self, root, path):
        """Remove the worktree at path."""

    @abstractmethod
    def delete_branch(self, root, branch):
        """Delete branch in root."""

    @abstractmethod
    def worktree_registered(self, root, path):
        """Return True if path is a registered worktree of root."""

from abc import ABC, abstractmethod


class GitPort(ABC):
    @abstractmethod
    def git(self, root, *args):
        pass

    @abstractmethod
    def git_ok(self, root, *args):
        pass

    @abstractmethod
    def is_git_repo(self, root):
        pass

    @abstractmethod
    def remote_url(self, root):
        pass

    @abstractmethod
    def branch_exists(self, root, branch):
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

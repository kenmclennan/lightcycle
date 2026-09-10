import os

from lightcycle.ports.git import GitOutcome, GitPort, GitReadError
from lightcycle.ports.teardown_ledger import TeardownLedgerPort


class FakeGit(GitPort, TeardownLedgerPort):
    def __init__(self, repos=None, is_repo=True, origin=None, registered=(),
                 dirty=(), events=None, branches=(), base=None, raises=(),
                 remote_unreadable=(), sync_result=True, clone_result=True,
                 sync_default_result=True, worktree_add_fails=False,
                 torn_down_branches=()):
        self._repos = set(repos) if repos is not None else None
        self._is_repo = is_repo
        self._origin = origin
        self._registered = set(registered)
        self.dirty = set(dirty)
        self._events = events
        self._branches = set(branches)
        self._base = base
        self._raises = set(raises)
        self._remote_unreadable = set(remote_unreadable)
        self._sync_result = sync_result
        self._clone_result = clone_result
        self._sync_default_result = sync_default_result
        self._worktree_add_fails = worktree_add_fails
        self._torn_down_branches = tuple(torn_down_branches)
        self.calls = []
        self.commits = []
        self.remote_deletes = []

    def _raise_if(self, method, root):
        if method in self._raises:
            raise GitReadError(
                "git %s failed in %s: fatal: not a git repository" % (method, root)
            )

    def add_worktree(self, root, path, branch, base, retries=0, backoff=0):
        self.calls.append(("add_worktree", root, path, branch, base))
        if self._worktree_add_fails:
            return GitOutcome(ok=False, detail="boom")
        return GitOutcome(ok=True)

    def prune_worktrees(self, root):
        pass

    def set_branch_upstream(self, root, branch, remote="origin"):
        self.calls.append(("set_branch_upstream", root, branch, remote))
        return GitOutcome(ok=True)

    def init_repo(self, root, branch="main"):
        self.calls.append(("init_repo", root, branch))

    def is_git_repo(self, root):
        self.calls.append(("is_git_repo", root))
        if self._repos is not None:
            return root in self._repos
        return self._is_repo

    def is_repo_root(self, root):
        self.calls.append(("is_repo_root", root))
        if self._repos is not None:
            return root in self._repos
        return True

    def remote_url(self, root):
        self.calls.append(("remote_url", root))
        if root in self._remote_unreadable:
            raise GitReadError(
                "git remote get-url failed in %s: fatal: not a git repository" % root
            )
        if isinstance(self._origin, dict):
            return self._origin.get(root)
        return self._origin

    def branch_exists(self, root, branch):
        self.calls.append(("branch_exists", root, branch))
        self._raise_if("branch_exists", root)
        return (root, branch) in self._branches

    def worktree_base(self, root):
        self.calls.append(("worktree_base", root))
        return self._base

    def sync_to_origin(self, root):
        self.calls.append(("sync_to_origin", root))
        return self._sync_result

    def clone(self, url, dest):
        self.calls.append(("clone", url, dest))
        return self._clone_result

    def clone_identity(self, identity, dest):
        self.calls.append(("clone_identity", identity, dest))
        if self._clone_result:
            os.makedirs(dest, exist_ok=True)
        return self._clone_result

    def sync_to_default_branch(self, root):
        self.calls.append(("sync_to_default_branch", root))
        return self._sync_default_result

    def remove_worktree(self, root, path):
        self.calls.append(("remove_worktree", root, path))

    def delete_branch(self, root, branch):
        self.calls.append(("delete_branch", root, branch))

    def delete_remote_branch(self, root, branch):
        self.calls.append(("delete_remote_branch", root, branch))
        self.remote_deletes.append((root, branch))

    def worktree_registered(self, root, path):
        self.calls.append(("worktree_registered", root, path))
        self._raise_if("worktree_registered", root)
        return path in self._registered

    def has_uncommitted(self, root):
        return root in self.dirty

    def commit_all(self, root, message):
        self.calls.append(("commit_all", root, message))

    def has_tracked_changes(self, root):
        return root in self.dirty

    def commit_tracked(self, root, message):
        self.commits.append((root, message))
        if self._events is not None:
            self._events.append(("commit", root))
        return True

    def common_dir(self, root):
        self.calls.append(("common_dir", root))
        self._raise_if("common_dir", root)
        return os.path.join(root, ".git")

    def created_worktrees(self):
        return [
            (root, args[0]) for (method, root, *args) in self.calls
            if method == "add_worktree"
        ]

    def torn_down_worktrees(self):
        return [
            (root, args[0]) for (method, root, *args) in self.calls
            if method == "remove_worktree"
        ]

    def created_branches(self):
        return [
            (root, args[1]) for (method, root, *args) in self.calls
            if method == "add_worktree" and args[2] is not None
        ]

    def torn_down_branches(self):
        if self._torn_down_branches:
            return self._torn_down_branches
        return [
            (root, args[0]) for (method, root, *args) in self.calls
            if method == "delete_branch"
        ]

    def torn_down_remote_branches(self):
        return [
            (root, args[0]) for (method, root, *args) in self.calls
            if method == "delete_remote_branch"
        ]

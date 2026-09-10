from lightcycle.ports.git import GitOutcome, GitPort


class FakeGit(GitPort):
    def __init__(self, repos=None, is_repo=True, origin=None, registered=(),
                 dirty=(), events=None):
        self._repos = set(repos) if repos is not None else None
        self._is_repo = is_repo
        self._origin = origin
        self._registered = set(registered)
        self.dirty = set(dirty)
        self._events = events
        self.calls = []
        self.commits = []
        self.remote_deletes = []

    def add_worktree(self, root, path, branch, base, retries, backoff):
        return GitOutcome(ok=True)

    def prune_worktrees(self, root):
        pass

    def set_branch_upstream(self, root, branch, remote="origin"):
        pass

    def init_repo(self, root, branch="main"):
        self.calls.append(("init_repo", root, branch))

    def is_git_repo(self, root):
        if self._repos is not None:
            return root in self._repos
        return self._is_repo

    def is_repo_root(self, root):
        return True

    def remote_url(self, root):
        return self._origin

    def branch_exists(self, root, branch):
        return False

    def worktree_base(self, root):
        return root

    def sync_to_origin(self, root):
        pass

    def clone(self, url, dest):
        return GitOutcome(ok=True)

    def clone_identity(self, identity, dest):
        return GitOutcome(ok=True)

    def sync_to_default_branch(self, root):
        pass

    def remove_worktree(self, root, path):
        pass

    def delete_branch(self, root, branch):
        pass

    def delete_remote_branch(self, root, branch):
        self.remote_deletes.append((root, branch))

    def worktree_registered(self, root, path):
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
        return root

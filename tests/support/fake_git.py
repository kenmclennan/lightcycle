import os

from lightcycle.ports.git import GitOutcome, GitPort, GitReadError
from lightcycle.ports.teardown_ledger import TeardownLedgerPort


class FakeGit(GitPort, TeardownLedgerPort):
    def __init__(self, repos=None, is_repo=True, origin=None, registered=(),
                 dirty=(), events=None, branches=(), base=None, raises=(),
                 remote_unreadable=(), sync_result=True, clone_result=True,
                 sync_default_result=True, worktree_add_fails=False,
                 torn_down_branches=(), head_shas=None, init_ok=True, commit_ok=True,
                 missing_identity=(), ref=None, ref_files=None, fetch_ok=True,
                 fetch_detail="boom", added=None, changed=None, ref_shas=None,
                 history=None, approvals=None, uncommitted=None):
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
        self._head_shas = head_shas or {}
        self._ref_shas = dict(ref_shas or {})
        self._init_ok = init_ok
        self._commit_ok = commit_ok
        self._missing_identity = list(missing_identity)
        self._ref = ref
        self._ref_files = {
            r: dict(files) for r, files in (ref_files or {}).items()
        }
        self._added = dict(added or {})
        self._approvals = dict(approvals or {})
        self._history = {k: list(v) for k, v in (history or {}).items()}
        self._changed = {k: list(v) for k, v in (changed or {}).items()}
        self._uncommitted = {k: list(v) for k, v in (uncommitted or {}).items()}
        self._fetch_ok = fetch_ok
        self._fetch_detail = fetch_detail
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
        return GitOutcome(ok=self._init_ok, detail="" if self._init_ok else "boom")

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
        self._raise_if("has_uncommitted", root)
        return root in self.dirty

    def commit_all(self, root, message):
        self.calls.append(("commit_all", root, message))
        return self._commit_ok

    def missing_identity(self, root):
        self.calls.append(("missing_identity", root))
        return list(self._missing_identity)

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

    def remote_head_sha(self, root, branch):
        self.calls.append(("remote_head_sha", root, branch))
        return self._head_shas.get((root, branch))

    def ref_sha(self, root, ref):
        self.calls.append(("ref_sha", root, ref))
        self._raise_if("ref_sha", root)
        return self._ref_shas.get((root, ref))

    def fetch_origin(self, root):
        self.calls.append(("fetch_origin", root))
        if self._fetch_ok:
            return GitOutcome(ok=True)
        return GitOutcome(ok=False, detail=self._fetch_detail)

    def default_ref(self, root):
        self.calls.append(("default_ref", root))
        return self._ref

    def list_files_at(self, root, ref):
        self.calls.append(("list_files_at", root, ref))
        return sorted(
            path for path in self._ref_files.get(ref, {})
            if not any(part.startswith(".") for part in path.split("/"))
        )

    def read_file_at(self, root, ref, path):
        self.calls.append(("read_file_at", root, ref, path))
        return self._ref_files.get(ref, {}).get(path)

    def added_at(self, root, ref, path):
        self.calls.append(("added_at", root, ref, path))
        return self._added.get(path)

    def last_change_at(self, root, ref, path):
        self.calls.append(("last_change_at", root, ref, path))
        return self._approvals.get(path, ())

    def commits_touching(self, root, ref, path, limit):
        self.calls.append(("commits_touching", root, ref, path, limit))
        self._raise_if("commits_touching", root)
        return list(self._history.get(path, []))[:limit]

    def changed_paths(self, root, base):
        self.calls.append(("changed_paths", root, base))
        self._raise_if("changed_paths", root)
        return list(self._changed.get((root, base), []))

    def uncommitted_paths(self, root):
        self.calls.append(("uncommitted_paths", root))
        self._raise_if("uncommitted_paths", root)
        return list(self._uncommitted.get(root, []))

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

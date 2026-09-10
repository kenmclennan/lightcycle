import os

from lightcycle.ports.git import GitOutcome, GitPort
from lightcycle.ports.github import Comment, GitHubEventsPort
from lightcycle.ports.spin import SpinPort
from lightcycle.ports.teardown_ledger import TeardownLedgerPort
from lightcycle.ports.workers import WorkersPort

_WORKTREE_BASE = "sim-base"


class RecordingGit(GitPort, TeardownLedgerPort):
    def __init__(self):
        self.calls = []
        self._worktrees = {}
        self._branches = set()

    def _record(self, method, root, *args):
        self.calls.append((root, method, args))

    def created_worktrees(self):
        return [
            (root, args[0]) for root, method, args in self.calls
            if method == "add_worktree"
        ]

    def torn_down_worktrees(self):
        return [(root, args[0]) for root, method, args in self.calls if method == "remove_worktree"]

    def created_branches(self):
        return [
            (root, args[1]) for root, method, args in self.calls
            if method == "add_worktree" and args[2] is not None
        ]

    def torn_down_branches(self):
        return [(root, args[0]) for root, method, args in self.calls if method == "delete_branch"]

    def torn_down_remote_branches(self):
        return [
            (root, args[0]) for root, method, args in self.calls
            if method == "delete_remote_branch"
        ]

    def add_worktree(self, root, path, branch, base, retries=0, backoff=0):
        self._record("add_worktree", root, path, branch, base)
        self._worktrees[(root, path)] = branch
        if base is not None:
            self._branches.add((root, branch))
        return GitOutcome(ok=True)

    def prune_worktrees(self, root):
        self._record("prune_worktrees", root)
        return GitOutcome(ok=True)

    def set_branch_upstream(self, root, branch, remote="origin"):
        self._record("set_branch_upstream", root, branch, remote)
        return GitOutcome(ok=True)

    def init_repo(self, root, branch="main"):
        self._record("init_repo", root, branch)
        return GitOutcome(ok=True)

    def is_git_repo(self, root):
        self._record("is_git_repo", root)
        return True

    def is_repo_root(self, root):
        self._record("is_repo_root", root)
        return True

    def remote_url(self, root):
        self._record("remote_url", root)
        return None

    def branch_exists(self, root, branch):
        self._record("branch_exists", root, branch)
        return (root, branch) in self._branches

    def worktree_base(self, root):
        self._record("worktree_base", root)
        return _WORKTREE_BASE

    def sync_to_origin(self, root):
        self._record("sync_to_origin", root)
        return True

    def clone(self, url, dest):
        self._record("clone", url, dest)
        return True

    def clone_identity(self, identity, dest):
        self._record("clone_identity", identity, dest)
        return True

    def sync_to_default_branch(self, root):
        self._record("sync_to_default_branch", root)
        return True

    def remove_worktree(self, root, path):
        self._record("remove_worktree", root, path)
        self._worktrees.pop((root, path), None)

    def delete_branch(self, root, branch):
        self._record("delete_branch", root, branch)
        self._branches.discard((root, branch))

    def delete_remote_branch(self, root, branch):
        self._record("delete_remote_branch", root, branch)

    def worktree_registered(self, root, path):
        self._record("worktree_registered", root, path)
        return (root, path) in self._worktrees

    def has_uncommitted(self, root):
        self._record("has_uncommitted", root)
        return False

    def commit_all(self, root, message):
        self._record("commit_all", root, message)

    def has_tracked_changes(self, root):
        self._record("has_tracked_changes", root)
        return False

    def commit_tracked(self, root, message):
        self._record("commit_tracked", root, message)

    def common_dir(self, root):
        self._record("common_dir", root)
        return os.path.join(root, ".git")


class ScriptedGitHub(GitHubEventsPort):
    def __init__(self):
        self._merged = set()
        self._conflicted = set()
        self._feedback = {}

    def script_merge(self, pr):
        self._merged.add(pr)

    def script_conflict(self, pr):
        self._conflicted.add(pr)

    def script_feedback(self, pr, body, author="reviewer"):
        self._feedback.setdefault(pr, []).append(
            Comment(author=author, body=body, is_top_level=True, created_at=1.0)
        )

    def is_merged(self, pr):
        hit = pr in self._merged
        self._merged.discard(pr)
        return hit

    def is_closed_unmerged(self, pr):
        return False

    def last_push_time(self, pr):
        return 0.0

    def is_conflicted(self, pr):
        hit = pr in self._conflicted
        self._conflicted.discard(pr)
        return hit

    def comments_since(self, pr, since):
        items = self._feedback.pop(pr, [])
        return [c for c in items if c.created_at > since]

    def pull_comments(self, pr, since):
        return []

    def reviews(self, pr, since):
        return []

    def head_sha(self, pr):
        return ""

    def changed_files(self, pr, sha):
        return frozenset()

    def ci_pending(self, pr, sha):
        return True


class NullWorkers(WorkersPort):
    def _refuse(self, name):
        raise AssertionError("not expected during simulation: %s" % name)

    def workers_state(self):
        self._refuse("workers_state")

    def pid_alive(self, pid, started=None):
        self._refuse("pid_alive")

    def reap(self):
        self._refuse("reap")

    def kill(self, pid):
        self._refuse("kill")

    def prune_workers(self, keep_dead=None):
        self._refuse("prune_workers")

    def set_step(self, spawnid, step):
        self._refuse("set_step")

    def step_for(self, spawnid):
        self._refuse("step_for")

    def mark_checked(self, spawnid):
        self._refuse("mark_checked")

    def log_mtime(self, path):
        self._refuse("log_mtime")

    def set_pid_started(self, spawnid, pid_started):
        self._refuse("set_pid_started")


class NullSpin(SpinPort):
    def _refuse(self, name):
        raise AssertionError("not expected during simulation: %s" % name)

    def load(self):
        self._refuse("load")

    def update(self, mutate):
        self._refuse("update")


class SimulateConfig:
    def __init__(self, real_config, specs_root, projects_root):
        self._real = real_config
        self._specs_root = specs_root
        self._projects_root = projects_root

    def __getattr__(self, name):
        return getattr(self._real, name)

    def specs_root(self):
        return self._specs_root

    def projects_root(self):
        return self._projects_root

    def spawn_id(self):
        return None
